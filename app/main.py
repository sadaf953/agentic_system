import json
import uuid
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from groq import AsyncGroq
import redis.asyncio as redis 
from app.config import GROQ_API_KEY, REDIS_URL
from app.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from contextlib import asynccontextmanager
from app.workers import retriever_worker, analyzer_worker, writer_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the worker loops in the background
    retriever_task = asyncio.create_task(retriever_worker())
    analyzer_task = asyncio.create_task(analyzer_worker())
    writer_task = asyncio.create_task(writer_worker())

    yield 

    retriever_task.cancel()
    analyzer_task.cancel()
    writer_task.cancel()

app = FastAPI(title="Agentic AI Multi-Step Task System", lifespan=lifespan)
groq_client = AsyncGroq(api_key=GROQ_API_KEY)

@app.get("/")
async def root():
    return {"message": "Agentic AI System is Online!"}

# Connection logic for Upstash Redis
# Use this simplified version
redis_client = redis.from_url(
    REDIS_URL, 
    decode_responses=True
)
class TaskRequest(BaseModel):
    prompt: str


# ---------------------------------------------------------
# ENDPOINT 1: THE ORCHESTRATOR (Receives task, starts pipeline)
# ---------------------------------------------------------
# main.py
# --- main.py ---

@app.post("/task")
async def submit_task(request: TaskRequest):
    task_id = str(uuid.uuid4())
    
    response = await groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {"role": "user", "content": request.prompt}
        ],
        model="llama-3.1-8b-instant",
        response_format={"type": "json_object"}
    )
    
    orchestrator_data = json.loads(response.choices[0].message.content)
    topic = orchestrator_data.get("topic_to_research", "General Research")
    
    task_payload = {
        "task_id": task_id,
        "original_prompt": request.prompt,
        "topic_to_research": topic
    }
    
    # Use APPEND instead of SET to initialize
    await redis_client.append(f"results:{task_id}", "Orchestrator: Task started. ")
    await redis_client.lpush("retriever_tasks", json.dumps(task_payload))
    
    return {"task_id": task_id}

@app.get("/stream/{task_id}")
async def stream_results(task_id: str):
    async def event_generator():
        last_index = 0
        while True:
            content = await redis_client.get(f"results:{task_id}") or ""
            if len(content) > last_index:
                new_text = content[last_index:]
                # This is the standard format for SSE
                yield new_text
                last_index = len(content)
                
                if "[DONE]" in new_text:
                    break
            await asyncio.sleep(0.2) 
    return StreamingResponse(event_generator(), media_type="text/plain")

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
from app.workers import queue_retriever 
from contextlib import asynccontextmanager
from app.workers import retriever_worker, analyzer_worker, writer_worker
from app.workers import results_store

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic ---
    # Start the worker loops in the background
    retriever_task = asyncio.create_task(retriever_worker())
    analyzer_task = asyncio.create_task(analyzer_worker())
    writer_task = asyncio.create_task(writer_worker())
    
    yield # The app runs here
    
    # --- Shutdown Logic ---
    # Clean up tasks if the server stops
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

# ... Your @app.post("/task") and @app.get("/stream") logic looks great ...
# Data model for the incoming user request
class TaskRequest(BaseModel):
    prompt: str



# ---------------------------------------------------------
# ENDPOINT 1: THE ORCHESTRATOR (Receives task, starts pipeline)
# ---------------------------------------------------------
@app.post("/task")
async def submit_task(request: TaskRequest):
    print("DEBUG: API reached submit_task")
    task_id = str(uuid.uuid4()) # Generate a unique ID for this task
    
    try:
        # 1. Ask Groq to figure out what needs to be researched
        response = await groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": request.prompt}
            ],
            model="llama-3.1-8b-instant", # Fast and cheap for orchestration
            response_format={"type": "json_object"} # Force JSON output
        )
        
        # 2. Parse the JSON from the Orchestrator
        orchestrator_data = json.loads(response.choices[0].message.content)
        topic = orchestrator_data.get("topic_to_research", "General Research")
        
        # 3. Create the payload for the first worker (Retriever)
        task_payload = {
            "task_id": task_id,
            "original_prompt": request.prompt,
            "topic_to_research": topic
        }
        
        # 4. Push to the Retriever's Queue and log the first status update
        await redis_client.lpush("retriever_tasks", json.dumps(task_payload))
        await redis_client.rpush(f"results:{task_id}", "Orchestrator: Task received. Breaking down steps...")
        await redis_client.rpush(f"results:{task_id}", f"Orchestrator: Passing topic '{topic}' to Retriever.")
        print("DEBUG: Task put into queue")
        # 5. Return t   he task_id so the user's browser can connect to the stream
        return {"task_id": task_id, "message": "Task started successfully."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# ENDPOINT 2: THE STREAM (Streams updates to the user)
# ---------------------------------------------------------
@app.get("/stream/{task_id}")
async def stream_results(task_id: str):
    async def event_generator():
        last_index = 0
        while True:
            content = results_store.get(task_id, "")
            # Send only the new part of the text
            if len(content) > last_index:
                new_text = content[last_index:]
                yield f"data: {new_text}\n\n"
                last_index = len(content)
                if "[DONE]" in new_text:
                    break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")






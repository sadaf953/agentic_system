import asyncio
import json
import redis.asyncio as redis # Add this
from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import GROQ_API_KEY, REDIS_URL # Add REDIS_URL
from app.prompts import RETRIEVER_SYSTEM_PROMPT, ANALYZER_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT
results_store = {}

QUEUE_RETRIEVER = "retriever_tasks"
QUEUE_ANALYZER = "analyzer_tasks"
QUEUE_WRITER = "writer_tasks"
redis_client = redis.from_url(REDIS_URL, decode_responses=True)
groq_client = AsyncGroq(api_key=GROQ_API_KEY)



@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def call_groq(system_prompt, user_prompt, json_mode=False, stream=False):
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    if stream:
        return await groq_client.chat.completions.create(messages=messages, model="llama-3.1-8b-instant", stream=True)
    response = await groq_client.chat.completions.create(
        messages=messages, model="llama-3.1-8b-instant", response_format={"type": "json_object"} if json_mode else None
    )
    return response

async def retriever_worker():
    print("Retriever Worker active...")
    while True:
        # Get task from Redis
        result = await redis_client.brpop("retriever_tasks", timeout=0)
        if result:
            _, task_json = result
            task = json.loads(task_json)
            task_id = task.get("task_id")
            await redis_client.append(f"results:{task_id}", "\nRetriever: Starting research... ")
            try:
                chat_completion = await groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": RETRIEVER_SYSTEM_PROMPT}, # Specialized Agent Role
                        {"role": "user", "content": f"Topic to research: {task.get('topic_to_research')}"}
                    ],
                    model="llama-3.1-8b-instant",
                )
                task["research_data"] = chat_completion.choices[0].message.content
            except Exception as e:
                print(f"❌ RETRIEVER CRASH: {e}")
                
                continue 

           
            # Push ONLY to Redis. No more asyncio.Queue!
            await redis_client.lpush("analyzer_tasks", json.dumps(task))
            await redis_client.append(f"results:{task_id}", "\n\n--- 🔍 RETRIEVER UPDATE ---\nResearch complete. Handing off to Analyzer for deeper insights.\n")
async def analyzer_worker():
    print("Analyzer Worker active (Real Batching Mode)...")
    batch = []
    MAX_BATCH_SIZE = 3
    BATCH_TIMEOUT = 5.0  # Seconds

    while True:
        try:
            # 1. Wait for at least ONE task to arrive (Blocking)
            if not batch:
                result = await redis_client.brpop("analyzer_tasks", timeout=BATCH_TIMEOUT)
                if result:
                    _, task_json = result
                    batch.append(json.loads(task_json))
            
            # 2. Try to grab more tasks quickly if they exist (Non-blocking)
            while len(batch) < MAX_BATCH_SIZE:
                # LPOP is non-blocking. If the queue is empty, it returns None
                extra_task_json = await redis_client.lpop("analyzer_tasks")
                if extra_task_json:
                    batch.append(json.loads(extra_task_json))
                else:
                    break # No more tasks in queue for now

            # 3. If we have a batch (or the timeout hit), process them!
            if batch:
                print(f"Analyzer: Processing batch of {len(batch)} tasks...")
                
                # Manual Batching: We send the whole list to the LLM in one prompt
                # This saves money and time!
                res = await call_groq(
                    ANALYZER_SYSTEM_PROMPT, 
                    f"Analyze these research reports: {json.dumps(batch)}", 
                    json_mode=True
                )
                
                analysis_results = json.loads(res.choices[0].message.content)
                
                # 4. Distribute the results back to individual tasks and hand off
                for task in batch:
                    task_id = task['task_id']
                    # Get the specific analysis for this task from the LLM JSON
                    task['analysis'] = analysis_results.get(task_id, "Analysis complete.")
                    
                    # Handoff each task in the batch to the Writer
                    await redis_client.lpush("writer_tasks", json.dumps(task))
                    await redis_client.append(f"results:{task_id}", "\n\n--- ANALYZER UPDATE ---\nBatch analysis complete.\n")
                # Clear the batch for the next round
                batch = []

        except Exception as e:
            print(f"❌ ANALYZER ERROR: {e}")
            batch = [] # Clear batch so we don't get stuck in a loop

async def writer_worker():
    print("Writer Worker active (Redis Mode)...")
    while True:
        result = await redis_client.brpop("writer_tasks", timeout=0)
        
        if result:
            _, task_json = result
            task = json.loads(task_json)
            task_id = task.get("task_id")
            print(f"Writer: RECEIVED TASK {task_id}")
            
            try:
                # 1. Update UI that we are starting
                await redis_client.append(f"results:{task_id}", "\nWriter: Generating final report...\n\n")

                # 2. Call Groq with streaming
                stream = await call_groq(
                    WRITER_SYSTEM_PROMPT, 
                    f"Prompt: {task['original_prompt']}\nAnalysis: {task['analysis']}", 
                    stream=True
                )
                
                # 3. Stream chunks DIRECTLY into Redis
                async for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        # NO MORE results_store[task_id]
                        # Use redis_client.append instead!
                        await redis_client.append(f"results:{task_id}", content)
                
                # 4. Mark as finished in Redis
                await redis_client.append(f"results:{task_id}", "\n\n[DONE]")
                print(f"Writer: Task {task_id} COMPLETED.")
                
            except Exception as e:
                print(f"CRITICAL ERROR in Writer: {e}")
                await redis_client.append(f"results:{task_id}", f"\n[ERROR]: {str(e)}")
async def main():
    await asyncio.gather(retriever_worker(), analyzer_worker(), writer_worker())


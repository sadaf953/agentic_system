import asyncio
import json
import redis.asyncio as redis # Add this
from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import GROQ_API_KEY, REDIS_URL # Add REDIS_URL
from app.prompts import RETRIEVER_SYSTEM_PROMPT, ANALYZER_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT
results_store = {}
# 1. Setup In-Memory Queues (Bypasses ISP/Firewall issues completely)
queue_retriever = asyncio.Queue()
queue_analyzer = asyncio.Queue()
queue_writer = asyncio.Queue()
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
        result = await redis_client.brpop("retriever_tasks", timeout=0)
        if result:
            _, task_json = result
            task = json.loads(task_json)
            task_id = task.get("task_id")
            print(f"Analyzer: GOT TASK {task['task_id']}")

            # --- STEP 1: UI UPDATE ---
            print(f"[{task_id}] Updating UI...")
            print(f"Retriever: PUSHING TO ANALYZER QUEUE {task_id}")
            await queue_analyzer.put(task)
            # await redis_client.rpush(f"results:{task_id}", "data: Retriever: Researching via Groq...")

            # --- STEP 2: GROQ CALL ---
            print(f"[{task_id}] Calling Groq...")
            try:
                chat_completion = await groq_client.chat.completions.create(
                    messages=[{"role": "user", "content": f"Research: {task.get('topic')}"}],
                    model="llama-3.1-8b-instant",
                )
                research_result = chat_completion.choices[0].message.content
                print(f"[{task_id}] Groq returned data successfully.")
            except Exception as e:
                print(f"❌ GROQ CRASH: {e}")
                continue 

            # --- STEP 3: PASS TO ANALYZER ---
            print(f"[{task_id}] Pushing to analyzer_tasks...")
            task["research_data"] = research_result
            await redis_client.lpush("analyzer_tasks", json.dumps(task))
            
            # --- STEP 4: FINAL UI UPDATE ---
            await redis_client.rpush(f"results:{task_id}", "data: Retriever: Done. Handing off to Analyzer.")
            print(f"[{task_id}] Retriever stage finished.")
async def analyzer_worker():
    print("Analyzer Worker active (Batching)...")
    batch = []
    while True:
        task = await queue_analyzer.get()
        print(f"Analyzer: GOT TASK {task['task_id']}")
        batch.append(task)
        if len(batch) >= 1: 
            res = await call_groq(ANALYZER_SYSTEM_PROMPT, json.dumps(batch), json_mode=True)
            results = json.loads(res.choices[0].message.content)
            # Logic: Assign analysis to task and move to writer
            task['analysis'] = results.get('analysis', 'Analysis complete.')
            await queue_writer.put(task)
            batch = []
        queue_analyzer.task_done()

async def writer_worker():
    print("Writer Worker active...")
    while True:
        task = await queue_writer.get()
        print(f"Writer: GOT TASK {task['task_id']}")
        
        try:
            # We call Groq with stream=True
            stream = await call_groq(WRITER_SYSTEM_PROMPT, f"Prompt: {task['original_prompt']}\nAnalysis: {task['analysis']}", stream=True)
            
            print(f"Writer: Streaming response for {task['task_id']}")
            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    # This pushes to the results store (which your stream endpoint uses)
                    # Use a dictionary or a queue to hold the result
                    results_store[task['task_id']] = results_store.get(task['task_id'], "") + content
                    print(content, end="", flush=True) # See it in Terminal 1
            
            print(f"\nTask {task['task_id']} complete.")
            results_store[task['task_id']] += "\n[DONE]"
            
        except Exception as e:
            print(f"CRITICAL ERROR in Writer: {e}")
            
        queue_writer.task_done()

async def main():
    await asyncio.gather(retriever_worker(), analyzer_worker(), writer_worker())


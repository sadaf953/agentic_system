import asyncio
import json
import redis.asyncio as redis
from app.config import REDIS_URL

async def check_queues():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    
    # 1. Check if the keys even exist
    retriever = await r.llen("retriever_tasks")
    analyzer = await r.llen("analyzer_tasks")
    writer = await r.llen("writer_tasks")
    
    print("\n--- REDIS QUEUE STATUS ---")
    print(f"Retriever Queue: {retriever} tasks")
    print(f"Analyzer Queue:  {analyzer} tasks")
    print(f"Writer Queue:    {writer} tasks")
    
    # 2. Peek at what's inside the Retriever queue
    if retriever > 0:
        first_task = await r.lrange("retriever_tasks", 0, 0)
        print(f"\nExample task in Retriever: {first_task}")

    # 3. List all task status updates (Results)
    # This finds all keys that look like results:TASK_ID
    keys = await r.keys("results:*")
    print(f"\nActive Result Streams: {len(keys)}")
    for k in keys[:3]: # Show first 3
        print(f" - {k}")

if __name__ == "__main__":
    asyncio.run(check_queues())
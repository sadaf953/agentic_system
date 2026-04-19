import os
import asyncio
import redis.asyncio as redis
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

async def test_connections():
    print("--- 🛠️ Starting Connection Tests ---")
    
    # 1. Test Environment Variables
    redis_url = os.getenv("REDIS_URL")
    groq_key = os.getenv("GROQ_API_KEY")
    
    if not redis_url or not groq_key:
        print("❌ Error: Missing credentials in .env file.")
        return

    # 2. Test Redis (Upstash)
    print(f"🔗 Connecting to Redis...")
    # Change the connection part to this:
    try:
    # We pass NOTHING but the URL. 
    # The URL now contains all the instructions (?ssl_cert_reqs=none)
        r = redis.from_url(redis_url, decode_responses=True)
        
        # We use 'ping' because it's the fastest way to check the handshake
        if await r.ping():
            print(f"✅ Redis: Connection Successful!")
    except Exception as e:
        print(f"❌ Redis Error: {e}")

        # 3. Test Groq API
        print(f"🔗 Connecting to Groq...")
        try:
            client = AsyncGroq(api_key=groq_key)
            chat_completion = await client.chat.completions.create(
                messages=[{"role": "user", "content": "Say 'Groq is ready'"}],
                model="llama-3.1-8b-instant",
            )
            print(f"✅ Groq: {chat_completion.choices[0].message.content}")
        except Exception as e:
            print(f"❌ Groq Error: {e}")

    print("--- 🏁 Tests Finished ---")

if __name__ == "__main__":
    asyncio.run(test_connections())
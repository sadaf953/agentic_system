# Agentic AI System for Multi-Step Tasks

This project is a high-performance, asynchronous multi-agent system designed to handle complex user tasks by breaking them into manageable steps. The system utilizes a decoupled architecture where specialized agents (Retriever, Analyzer, and Writer) communicate via a Redis-backed message queue.

## System Architecture

The system is designed for horizontal scalability and resilience. Unlike "black-box" frameworks, this system implements manual orchestration and batching logic.

1.  **Orchestrator (FastAPI):** Receives the user prompt, determines the research topic, and pushes the initial task to Redis.
2.  **Retriever Agent:** Pops tasks from Redis, performs research using Groq (LLM), and pushes data to the Analyzer queue.
3.  **Analyzer Agent (Batching):** Implements manual batching logic. It waits for 3 tasks or a 5-second timeout to process research reports in a single LLM call to optimize throughput and cost.
4.  **Writer Agent (Streaming):** Receives analyzed data and streams the final report token-by-token back to the Redis result store.
5.  **Stream Endpoint:** A FastAPI `StreamingResponse` that polls Redis and delivers real-time updates to the user via Server-Sent Events (SSE).

## 🏗 System Architecture
![System Architecture](docs/architecture.png)


##  Technical Highlights

-   **Async Inference Pipeline:** Built entirely on `asyncio` for non-blocking I/O.
-   **Distributed Message Queue:** Uses Redis (`BRPOP`/`LPUSH`) for inter-agent communication.
-   **Manual Batching:** Analyzer agent groups multiple tasks to reduce LLM API overhead.
-   **Real-time Streaming:** Token-level streaming from background workers to the UI via Redis `APPEND`.
-   **Resilience:** Implements `tenacity` for exponential backoff retries on LLM inference.

##  Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   cd agentic_system
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables:**
   Create a `.env` file in the root directory:
   ```text
   GROQ_API_KEY=your_groq_api_key
   REDIS_URL=your_upstash_or_local_redis_url
   ```

## How to Run (3-Terminal Method)

To observe the agentic flow and internal communication, open three terminal windows:

### Terminal 1: The Application Server
Start the FastAPI server. This also initializes the Retriever, Analyzer, and Writer background workers.
```bash
uvicorn app.main:app --reload
```

### Terminal 2: The Redis Monitor
Monitor the real-time message passing, task handoffs, and result streaming between agents.

1. **Open a new terminal tab.**
2. **Execute the Monitor command via Redis CLI:**
   * **If using Local Redis:**
     ```bash
     redis-cli MONITOR
     ```
   * **If using Upstash (Cloud) Redis:**
     ```bash
     # Copy the REDIS_URL from your .env and append MONITOR
     redis-cli -u redis://default:YOUR_PASSWORD@YOUR_ENDPOINT.upstash.io:6379 MONITOR
     ```
3. **What to look for:**
   * `BRPOP`: An agent is pulling a task from the queue.
   * `LPUSH`: An agent is handing a task to the next step in the pipeline.
   * `APPEND`: The system is streaming real-time updates to the result key.

### Terminal 3: Task Submission
Trigger a new task via CURL.
```bash
curl -X POST http://localhost:8000/task \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Research the cognitive benefits of audiobooks vs reading."}'
```

### Final Step: View the Result
Copy the `task_id` returned in Terminal 3 and open your browser to:
`http://localhost:8000/stream/YOUR_TASK_ID`


### Utility Scripts
- `test_redis.py`: A sanity check to verify the connection to the Upstash Redis instance.
- `debug_redis.py`: A monitoring tool used during development to track real-time task counts in each agent queue.

### 🧹 Maintenance: Clearing the System
If you encounter Redis "WRONGTYPE" errors or want to clear stuck tasks from the queues, run this one-liner in your terminal:

```bash
python -c "import asyncio; import redis.asyncio as redis; from app.config import REDIS_URL; r=redis.from_url(REDIS_URL); asyncio.run(r.flushdb()); print('✅ Redis database cleared successfully!')"


## Project Explanation Video
[Link to Drive Video Here]

## Post-Mortem
Detailed documentation on scaling issues, design decisions, and trade-offs can be found in `POST_MORTEM.md`.
# Post-Mortem: Agentic AI System

### 1. One Scaling Issue Encountered
The most significant issue encountered was a persistent "glitch" where the system would hang or show blank screens during agent handoffs. Initially, I struggled with Redis connection timeouts and data type conflicts. To ensure the logic was sound, I temporarily pivoted to in-memory queues for validation.

**The Solution:** I refactored the system back to Redis by standardizing a strict command protocol to solve the synchronization issues:
- **Task Handoffs:** I used `LPUSH` to send tasks and `BRPOP` to ensure workers waited efficiently for new data without "spinning" or crashing.
- **Result Streaming:** I resolved the "blank screen" issue by using `APPEND` and `GET`. This allowed the background workers to stream LLM tokens into a Redis string that the FastAPI endpoint could read from simultaneously. This change ensured the system remained stateful and distributed across different process contexts.

### 2. One Design Decision I Would Change
I would move the workers out of the FastAPI `lifespan` and into a dedicated, standalone worker service. Currently, the workers share the same CPU cycle and process as the web server. While this works for a single-instance demo, a true production-grade system would run these as separate containers to allow the API to stay responsive even when agents are performing heavy batch processing.

### 3. Trade-offs Made (Batching vs. Real-Time Latency)
I implemented a **Manual Batching** logic in the Analyzer agent, which forced a trade-off between **Immediate Response** and **System Throughput**.
- **The Trade-off:** By implementing a 5-second `BATCH_TIMEOUT` or a `MAX_BATCH_SIZE` of 3, the first task in a batch has to wait for others to arrive.
- **The Benefit:** This manual batching prevents the system from hitting Groq API rate limits and significantly reduces the total number of LLM calls, making the system much more scalable and cost-effective under high load.
```

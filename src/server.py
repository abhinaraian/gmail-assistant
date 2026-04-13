"""
FastAPI server — runs the Gmail agent and streams output to the Chrome extension via SSE.
"""

import asyncio
import json
import queue
import threading
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Gmail Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global agent state ──────────────────────────────────────────────────────
_message_queue: queue.Queue = queue.Queue()
_agent_running: bool = False
_agent_thread: Optional[threading.Thread] = None


def _enqueue(text: str, msg_type: str = "log") -> None:
    """Called by the agent to push a message into the SSE queue."""
    # Split multi-line messages so each line is a discrete event
    for line in text.split("\n"):
        _message_queue.put({"type": msg_type, "text": line})


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/status")
async def get_status():
    return {"running": _agent_running, "ready": True}


class RunRequest(BaseModel):
    instruction: str = (
        "Analyze my inbox and organize it with smart, meaningful labels. "
        "Be comprehensive and aim to label at least 75% of my emails."
    )


@app.post("/run")
async def run_agent(req: RunRequest):
    global _agent_running, _agent_thread

    if _agent_running:
        return {"error": "Agent is already running"}

    # Drain stale messages from a previous run
    while not _message_queue.empty():
        try:
            _message_queue.get_nowait()
        except queue.Empty:
            break

    def _run_in_thread():
        global _agent_running
        _agent_running = True
        try:
            from src.agent import GmailAgent
            agent = GmailAgent(log_callback=_enqueue)
            agent.run(req.instruction)
            _enqueue("✓ Organization complete!", "done")
        except Exception as exc:
            _enqueue(f"Error: {exc}", "error")
        finally:
            _agent_running = False

    _agent_thread = threading.Thread(target=_run_in_thread, daemon=True)
    _agent_thread.start()
    return {"status": "started"}


@app.get("/stream")
async def stream_events(request: Request):
    """SSE endpoint — stays open and pushes messages as the agent runs."""

    async def generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = _message_queue.get_nowait()
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                # Keep-alive ping every 500 ms
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                await asyncio.sleep(0.5)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

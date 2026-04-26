from __future__ import annotations

import asyncio
import csv
import uuid
from io import StringIO
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter

from app.chat_store import ChatStore
from app.schemas import (
    GenerateRequest,
    GenerateResponse,
    MessageIn,
    MessageOut,
    SessionCreateOut,
    SessionOut,
)
from app.agent.pipeline import AgentPipeline

app = FastAPI(title="LocalScript API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = AgentPipeline()
store = ChatStore()

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "localscript" / "dist"

# ── API routes (shared router, mounted at both / and /api) ───────────

api = APIRouter()


@api.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    result = await pipeline.run(req.prompt)
    if result.is_question:
        return GenerateResponse(
            code="",
            message=result.full_response,
            is_valid=None,
            is_question=True,
            iterations=result.iterations,
        )
    return GenerateResponse(
        code=result.code if result.code else result.full_response,
        message="",
        is_valid=result.is_valid,
        is_question=False,
        iterations=result.iterations,
    )


@api.post("/chat/sessions", response_model=SessionCreateOut)
async def create_session():
    session = await store.create_session()
    return SessionCreateOut(id=session.id)


@api.get("/chat/sessions", response_model=list[SessionOut])
async def list_sessions():
    sessions = await store.list_sessions()
    out = []
    for s in sessions:
        last_msg = s.messages[-1].content if s.messages else None
        out.append(
            SessionOut(
                id=s.id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
                last_message=last_msg[:120] if last_msg else None,
            )
        )
    return out


@api.get("/chat/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_messages(session_id: uuid.UUID):
    try:
        messages = await store.get_messages(session_id)
    except ValueError:
        return []
    return [
        MessageOut(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            lua_code=m.lua_code,
            is_valid=m.is_valid,
            is_question=m.is_question,
            created_at=m.created_at,
        )
        for m in messages
    ]


@api.post("/chat/sessions/{session_id}/messages", response_model=MessageOut)
async def send_message(session_id: uuid.UUID, msg: MessageIn):
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await store.add_message(
        session_id=session_id,
        role="user",
        content=msg.content,
    )

    messages = await store.get_messages(session_id)
    chat_history = [{"role": m.role, "content": m.content} for m in messages]

    result = await pipeline.run(
        msg.content,
        chat_history=chat_history,
        existing_summary=session.summary,
        summarized_count=session.summarized_count,
    )

    if result.updated_summary and result.updated_summary != session.summary:
        await store.update_summary(
            session_id, result.updated_summary, result.summarized_count,
        )

    assistant_msg = await store.add_message(
        session_id=session_id,
        role="assistant",
        content=result.full_response,
        lua_code=result.code if result.code else None,
        is_valid=result.is_valid,
        is_question=result.is_question,
    )

    return MessageOut(
        id=assistant_msg.id,
        session_id=assistant_msg.session_id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        lua_code=assistant_msg.lua_code,
        is_valid=assistant_msg.is_valid,
        is_question=assistant_msg.is_question,
        created_at=assistant_msg.created_at,
    )


# ── GPU monitoring state ──────────────────────────────────────────────

_gpu_peak: dict[int, float] = {}


def _get_ollama_gpu_ids() -> set[int] | None:
    """Detect which GPU(s) Ollama uses from its CUDA_VISIBLE_DEVICES."""
    import os
    pid_file = Path(__file__).resolve().parent.parent / ".local" / "ollama.pid"
    try:
        if pid_file.exists():
            pid = pid_file.read_text().strip()
            environ_path = Path(f"/proc/{pid}/environ")
            if environ_path.exists():
                env_data = environ_path.read_bytes().split(b'\x00')
                for entry in env_data:
                    text = entry.decode(errors="ignore")
                    if text.startswith("CUDA_VISIBLE_DEVICES="):
                        ids = text.split("=", 1)[1]
                        return {int(x.strip()) for x in ids.split(",") if x.strip().isdigit()}
    except Exception:
        pass
    cuda_env = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda_env:
        return {int(x.strip()) for x in cuda_env.split(",") if x.strip().isdigit()}
    return None


async def _query_gpu() -> list[dict] | None:
    """Query nvidia-smi asynchronously. Returns None if unavailable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            return None

        ollama_gpus = _get_ollama_gpu_ids()

        gpus = []
        reader = csv.reader(StringIO(stdout.decode().strip()))
        for row in reader:
            if len(row) < 6:
                continue
            gpu_id = int(row[0].strip())

            if ollama_gpus is not None and gpu_id not in ollama_gpus:
                continue

            mem_used = float(row[2].strip())

            if gpu_id not in _gpu_peak or mem_used > _gpu_peak[gpu_id]:
                _gpu_peak[gpu_id] = mem_used

            gpus.append({
                "gpu_id": gpu_id,
                "name": row[1].strip(),
                "memory_used_mb": mem_used,
                "memory_total_mb": float(row[3].strip()),
                "utilization_pct": int(row[4].strip()),
                "temperature_c": int(row[5].strip()),
                "peak_memory_mb": _gpu_peak[gpu_id],
            })
        return gpus
    except (FileNotFoundError, asyncio.TimeoutError):
        return None


@api.get("/gpu/stats")
async def gpu_stats():
    gpus = await _query_gpu()
    if gpus is None:
        return {"available": False, "gpus": []}

    for g in gpus:
        g["memory_used_gb"] = round(g["memory_used_mb"] / 1024, 2)
        g["memory_total_gb"] = round(g["memory_total_mb"] / 1024, 2)
        g["peak_memory_gb"] = round(g["peak_memory_mb"] / 1024, 2)
        g["usage_pct"] = round(g["memory_used_mb"] / g["memory_total_mb"] * 100, 1) if g["memory_total_mb"] > 0 else 0
        g["within_8gb_limit"] = g["peak_memory_mb"] <= 8192

    return {"available": True, "gpus": gpus}


@api.post("/gpu/reset-peak")
async def gpu_reset_peak():
    _gpu_peak.clear()
    return {"status": "ok"}


# Mount the same router at both prefixes:
#   /generate, /chat/...        — for direct backend access and Docker nginx
#   /api/generate, /api/chat/.. — for unified mode (frontend served by uvicorn)
app.include_router(api)
app.include_router(api, prefix="/api")

# ── Serve frontend (only when built) ────────────────────────────────

if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")

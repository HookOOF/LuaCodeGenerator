from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


@dataclass
class MessageData:
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    lua_code: str | None = None
    is_valid: bool | None = None
    is_question: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SessionData:
    id: uuid.UUID
    title: str | None = None
    summary: str | None = None
    summarized_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages: list[MessageData] = field(default_factory=list)


def _session_to_dict(session: SessionData) -> dict:
    return {
        "id": str(session.id),
        "title": session.title,
        "summary": session.summary,
        "summarized_count": session.summarized_count,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "messages": [
            {
                "id": str(m.id),
                "session_id": str(m.session_id),
                "role": m.role,
                "content": m.content,
                "lua_code": m.lua_code,
                "is_valid": m.is_valid,
                "is_question": m.is_question,
                "created_at": m.created_at.isoformat(),
            }
            for m in session.messages
        ],
    }


def _dict_to_session(d: dict) -> SessionData:
    messages = [
        MessageData(
            id=uuid.UUID(m["id"]),
            session_id=uuid.UUID(m["session_id"]),
            role=m["role"],
            content=m["content"],
            lua_code=m.get("lua_code"),
            is_valid=m.get("is_valid"),
            is_question=m.get("is_question", False),
            created_at=datetime.fromisoformat(m["created_at"]),
        )
        for m in d.get("messages", [])
    ]
    return SessionData(
        id=uuid.UUID(d["id"]),
        title=d.get("title"),
        summary=d.get("summary"),
        summarized_count=d.get("summarized_count", 0),
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
        messages=messages,
    )


class ChatStore:
    def __init__(self, storage_dir: str | None = None) -> None:
        self._dir = Path(storage_dir or settings.chat_storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def _lock_for(self, session_id: uuid.UUID) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def _path(self, session_id: uuid.UUID) -> Path:
        return self._dir / f"{session_id}.json"

    def _read_sync(self, session_id: uuid.UUID) -> SessionData | None:
        p = self._path(session_id)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return _dict_to_session(data)

    def _write_sync(self, session: SessionData) -> None:
        p = self._path(session.id)
        p.write_text(
            json.dumps(_session_to_dict(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def create_session(self) -> SessionData:
        session = SessionData(id=uuid.uuid4())
        await asyncio.to_thread(self._write_sync, session)
        return session

    async def get_session(self, session_id: uuid.UUID) -> SessionData | None:
        return await asyncio.to_thread(self._read_sync, session_id)

    async def list_sessions(self) -> list[SessionData]:
        def _list() -> list[SessionData]:
            sessions: list[SessionData] = []
            for p in self._dir.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    sessions.append(_dict_to_session(data))
                except (json.JSONDecodeError, KeyError):
                    continue
            sessions.sort(key=lambda s: s.updated_at, reverse=True)
            return sessions

        return await asyncio.to_thread(_list)

    async def add_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        lua_code: str | None = None,
        is_valid: bool | None = None,
        is_question: bool = False,
    ) -> MessageData:
        async with self._lock_for(session_id):
            session = await asyncio.to_thread(self._read_sync, session_id)
            if session is None:
                raise ValueError(f"Session {session_id} not found")

            msg = MessageData(
                id=uuid.uuid4(),
                session_id=session_id,
                role=role,
                content=content,
                lua_code=lua_code,
                is_valid=is_valid,
                is_question=is_question,
            )
            session.messages.append(msg)
            session.updated_at = datetime.now(timezone.utc)

            if not session.title and role == "user":
                session.title = content[:60]

            await asyncio.to_thread(self._write_sync, session)
            return msg

    async def update_summary(
        self,
        session_id: uuid.UUID,
        summary: str,
        summarized_count: int,
    ) -> None:
        async with self._lock_for(session_id):
            session = await asyncio.to_thread(self._read_sync, session_id)
            if session is None:
                raise ValueError(f"Session {session_id} not found")
            session.summary = summary
            session.summarized_count = summarized_count
            await asyncio.to_thread(self._write_sync, session)

    async def get_messages(self, session_id: uuid.UUID) -> list[MessageData]:
        session = await asyncio.to_thread(self._read_sync, session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        return session.messages

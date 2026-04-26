from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    code: str = ""
    message: str = ""
    is_valid: bool | None = None
    is_question: bool = False
    iterations: int = 1


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    last_message: str | None = None


class MessageIn(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    lua_code: str | None
    is_valid: bool | None
    is_question: bool = False
    created_at: datetime


class SessionCreateOut(BaseModel):
    id: uuid.UUID

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class MemoryType(str, Enum):
    decision = "decision"
    context = "context"
    note = "note"
    bug = "bug"


class Memory(BaseModel):
    id: str
    content: str
    type: MemoryType = MemoryType.note
    tags: list[str] = []
    feature_id: Optional[str] = None
    prd_id: Optional[str] = None
    plan_id: Optional[str] = None
    qa_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

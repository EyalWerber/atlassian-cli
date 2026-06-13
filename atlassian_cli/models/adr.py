from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AdrStatus(str, Enum):
    proposed = "proposed"
    accepted = "accepted"
    deprecated = "deprecated"
    superseded = "superseded"


class ADR(BaseModel):
    id: str
    title: str
    status: AdrStatus = AdrStatus.proposed
    context: str
    decision: str
    consequences: str
    feature_id: Optional[str] = None
    memory_id: Optional[str] = None
    confluence_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

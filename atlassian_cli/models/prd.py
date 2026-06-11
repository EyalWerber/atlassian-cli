from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PRDStatus(str, Enum):
    draft = "draft"
    published = "published"


class PRD(BaseModel):
    id: str
    title: str
    summary: str
    problem: str
    personas: str
    stories: str
    business_value: str
    requirements: str
    nfr: str
    considerations: str = ""
    risks: str
    metrics: str
    out_of_scope: str
    future_enhancements: str = ""
    feature_id: Optional[str] = None
    confluence_page_id: Optional[str] = None
    confluence_url: Optional[str] = None
    status: PRDStatus = PRDStatus.draft
    created_at: datetime
    updated_at: datetime

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class QAPlanStatus(str, Enum):
    draft = "draft"
    executed = "executed"


class QAScenario(BaseModel):
    title: str
    steps: list[str]
    expected_result: str
    bug_key: Optional[str] = None
    log_path: Optional[str] = None  # scaffolded — open idea, product-specific
    prd_section: Optional[str] = None


class QAPlan(BaseModel):
    id: str
    feature_id: str
    prd_id: str
    qa_base_url: str
    scenarios: list[QAScenario]
    status: QAPlanStatus = QAPlanStatus.draft
    created_at: datetime
    updated_at: datetime
    confluence_page_id: Optional[str] = None
    confluence_url: Optional[str] = None

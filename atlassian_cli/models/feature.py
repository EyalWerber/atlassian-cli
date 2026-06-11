from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class FeatureType(str, Enum):
    new_feature = "new-feature"
    enhancement = "enhancement"
    bug = "bug"
    refactor = "refactor"
    tech_debt = "tech-debt"
    research = "research"
    docs = "docs"
    architecture = "architecture"


class FeatureStatus(str, Enum):
    draft = "draft"
    active = "active"
    completed = "completed"


class Feature(BaseModel):
    id: str
    name: str
    type: FeatureType
    description: str
    prd_id: Optional[str] = None
    jira_key: Optional[str] = None
    status: FeatureStatus = FeatureStatus.draft
    created_at: datetime
    updated_at: datetime

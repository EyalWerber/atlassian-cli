from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PlanStatus(str, Enum):
    draft = "draft"
    created = "created"


class Task(BaseModel):
    title: str
    description: str
    jira_key: Optional[str] = None


class Story(BaseModel):
    title: str
    description: str
    tasks: list[Task]
    jira_key: Optional[str] = None


class Epic(BaseModel):
    title: str
    description: str
    stories: list[Story]
    jira_key: Optional[str] = None


class Plan(BaseModel):
    id: str
    feature_id: str
    prd_id: str
    epics: list[Epic]
    status: PlanStatus = PlanStatus.draft
    created_at: datetime
    updated_at: datetime

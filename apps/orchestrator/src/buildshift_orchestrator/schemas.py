from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str
    acceptance_criteria: str = ""
    owned_paths: list[str] = Field(default_factory=list)
    deps: list[str] = Field(default_factory=list)
    tier: str = "T1"
    difficulty: str = "normal"
    budget_usd: float | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    state: str
    tier: str
    difficulty: str
    role: str
    acceptance_criteria: str
    owned_paths: list
    budget_usd: Decimal
    spent_usd: Decimal
    attempts: int
    max_attempts: int
    branch: str | None
    pr_url: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class KillSwitchIn(BaseModel):
    enabled: bool


class KillSwitchOut(BaseModel):
    enabled: bool


class HealthOut(BaseModel):
    status: str
    kill_switch: bool
    version: str

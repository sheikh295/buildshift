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
    stage: str | None = None
    acceptance_criteria: str
    owned_paths: list
    budget_usd: Decimal
    spent_usd: Decimal
    attempts: int
    max_attempts: int
    branch: str | None
    pr_url: str | None
    error: str | None
    plan_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    review_verdict: str | None = None
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


class PrdIndexIn(BaseModel):
    markdown: str
    source_name: str = "uploaded.md"


class PrdProductOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    summary: str
    build_order: int
    status: str
    source_path: str | None = None

    model_config = {"from_attributes": True}


class PrdIndexOut(BaseModel):
    products: list[PrdProductOut]


class PlanProposeIn(BaseModel):
    product_id: uuid.UUID
    max_tickets: int = 3


class PlanOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    status: str
    goals: list
    tickets: list
    diff: dict
    estimated_spend_usd: Decimal
    approved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanApproveOut(BaseModel):
    plan_id: str
    task_ids: list[str]
    status: str


class KickoffOut(BaseModel):
    product_id: str
    slug: str
    requirements: int
    human_items: int

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


class EventOut(BaseModel):
    id: int
    ts: datetime
    task_id: uuid.UUID | None = None
    role: str | None = None
    model: str | None = None
    tier: str | None = None
    kind: str
    status: str | None = None
    summary: str | None = None
    cost_usd: Decimal
    payload: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class HumanItemOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    kind: str
    summary: str
    needed_by: str | None = None
    status: str
    reply: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HumanItemCreate(BaseModel):
    kind: str = "question"
    summary: str
    needed_by: str | None = None
    task_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None


class HumanItemReplyIn(BaseModel):
    reply: str


class RuntimeSettingsOut(BaseModel):
    version: int = 1
    roles: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=dict)
    harness: str = "mock"
    multi_role_pipeline: bool = True
    poll_interval_sec: float = 2.0
    proving_repo_url: str = ""
    proving_repo_branch: str = "main"
    kill_switch: bool = False
    ui: dict = Field(default_factory=dict)
    updated_at: datetime | None = None


class RuntimeSettingsIn(BaseModel):
    """Partial update; nested roles/limits are deep-merged."""

    roles: dict | None = None
    limits: dict | None = None
    harness: str | None = None
    multi_role_pipeline: bool | None = None
    poll_interval_sec: float | None = None
    proving_repo_url: str | None = None
    proving_repo_branch: str | None = None
    kill_switch: bool | None = None
    ui: dict | None = None


class EodDigestOut(BaseModel):
    day: str
    counts_by_state: dict[str, int]
    merged: int
    reviewing: int
    blocked_human: int
    parked: int
    failed: int
    spend_usd: float
    open_hitl: int
    recent_events: list[EventOut]
    risks: list[str]

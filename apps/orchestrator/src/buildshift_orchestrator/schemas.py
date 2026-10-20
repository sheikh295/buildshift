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
    project_id: uuid.UUID | None = None
    sprint_id: uuid.UUID | None = None
    epic_id: uuid.UUID | None = None
    parent_epic: str | None = None
    review_verdict: str | None = None
    pause_notes: str | None = None
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
    project_id: uuid.UUID | None = None
    slug: str
    title: str
    summary: str
    build_order: int
    status: str
    source_path: str | None = None

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    title: str
    slug: str | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    status: str
    prd_path: str | None = None
    has_prd: bool = False
    repo_url: str | None = None
    repo_branch: str = "main"
    repo_path: str | None = None
    repo_synced_at: datetime | None = None
    has_repo: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectDetailOut(BaseModel):
    project: ProjectOut
    modules: list[PrdProductOut]
    sprint_count: int
    open_hitl: int


class ProjectRepoIn(BaseModel):
    """Connect a git remote (or local path) that workers will clone and land onto."""

    repo_url: str
    repo_branch: str = "main"
    sync: bool = True


class ProjectPrdIn(BaseModel):
    markdown: str
    source_name: str = "uploaded.md"


class ProjectPrdOut(BaseModel):
    project_id: str
    modules: int
    module_ids: list[str]


class SprintProposeIn(BaseModel):
    """How large a sprint to plan. capacity_hours is a ceiling (1–40); work is not padded."""

    capacity_hours: float = 6.0
    mode: str = "hours"  # reserved; sizing is driven by capacity_hours


class SprintOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    mode: str
    status: str
    capacity_hours: Decimal
    goals: list
    estimated_spend_usd: Decimal
    estimated_hours: Decimal
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EpicOut(BaseModel):
    id: uuid.UUID
    sprint_id: uuid.UUID
    project_id: uuid.UUID
    product_id: uuid.UUID | None = None
    title: str
    status: str
    sort_order: int

    model_config = {"from_attributes": True}


class SprintDetailOut(BaseModel):
    sprint: SprintOut
    epics: list[dict]
    ungrouped_tasks: list[TaskOut] = Field(default_factory=list)


class SprintKickoffOut(BaseModel):
    sprint_id: str
    status: str
    task_ids: list[str]
    task_count: int


class SprintPauseOut(BaseModel):
    sprint_id: str
    status: str
    inflight: int
    message: str


class HitlTreeItem(BaseModel):
    id: uuid.UUID
    kind: str
    summary: str
    status: str
    task_id: uuid.UUID | None = None
    needed_by: str | None = None
    created_at: datetime


class HitlSprintNode(BaseModel):
    sprint_id: uuid.UUID | None
    sprint_label: str
    count: int
    items: list[HitlTreeItem]


class HitlProjectNode(BaseModel):
    project_id: uuid.UUID | None
    project_title: str
    count: int
    sprints: list[HitlSprintNode]


class HitlTreeOut(BaseModel):
    projects: list[HitlProjectNode]


class UsageBucket(BaseModel):
    key: str
    label: str
    cost_usd: float
    tokens_in: int = 0
    tokens_out: int = 0
    run_count: int = 0
    models: dict[str, float] = Field(default_factory=dict)


class UsageOut(BaseModel):
    from_day: str | None = None
    to_day: str | None = None
    group_by: str
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    buckets: list[UsageBucket]
    model_totals: dict[str, float] = Field(default_factory=dict)


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
    project_id: uuid.UUID | None = None
    sprint_id: uuid.UUID | None = None
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
    project_id: uuid.UUID | None = None
    sprint_id: uuid.UUID | None = None


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


class EodSessionOut(BaseModel):
    run_id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    role: str
    model: str | None
    status: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    started_at: datetime | None
    ended_at: datetime | None
    duration_sec: float | None = None


class EodDigestOut(BaseModel):
    day: str
    project_id: uuid.UUID | None = None
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
    sessions: list[EodSessionOut] = Field(default_factory=list)
    agents: list[dict] = Field(default_factory=list)
    hierarchy: list[dict] = Field(default_factory=list)

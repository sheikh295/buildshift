from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://buildshift:buildshift@localhost:5432/buildshift"
    orchestrator_host: str = "0.0.0.0"
    orchestrator_port: int = 8080

    task_budget_usd: float = 3.0
    daily_budget_usd: float = 60.0
    max_parallel_workers: int = 2
    max_attempts_per_tier: int = 2

    harness: str = "mock"
    worker_image: str = "buildshift-worker:local"
    worker_network: str = "buildshift_default"
    docker_host: str | None = None

    data_dir: Path = Path("/data")
    # Absolute path to the same data dir on the Docker host (required for docker-from-docker mounts)
    host_data_dir: Path | None = None
    repo_root: Path = Path("/repo")  # monorepo mount inside orchestrator container
    migrations_dir: Path = Path("/app/migrations")
    router_config_path: Path = Path("/app/config/router.yaml")
    # When true, ad-hoc POST /tasks still works (Week 1). Plan-approved tasks use multi-role.
    multi_role_pipeline: bool = True

    @field_validator("host_data_dir", mode="before")
    @classmethod
    def _empty_path_to_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    proving_repo_url: str = ""
    proving_repo_branch: str = "main"
    github_token: str = ""
    github_api_url: str = "https://api.github.com"

    litellm_url: str = "http://litellm:4000"
    litellm_master_key: str = "sk-buildshift-local"
    default_implementer_model: str = "claude-sonnet-4-5"

    # Office / API auth (empty = open, for local smoke). Dashboard sends Bearer or X-Operator-Token.
    operator_token: str = ""

    poll_interval_sec: float = 2.0

    # CORS origins for dashboard (comma-separated). Empty → allow localhost:3000.
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()

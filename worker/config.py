"""Worker configuration — loaded from environment or .env file."""

from __future__ import annotations

import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Settings for the BSGateway worker process."""

    # BSGateway API URL
    server_url: str = "http://localhost:8000"

    # Worker identity (from registration)
    worker_token: str = ""
    worker_name: str = socket.gethostname()

    # Install token — required ONLY on first run to register the worker.
    # Minted by an admin via the gateway UI. Once registered, worker_token is
    # saved to .env and this is no longer used.
    install_token: str = ""

    # Polling
    poll_interval_seconds: int = 5
    # Short sleep when at max_parallel_tasks capacity, waiting for one to finish.
    capacity_wait_seconds: float = 1.0
    # Maximum tasks to request per poll call, regardless of free slots.
    poll_batch_max: int = 5

    # Execution
    max_parallel_tasks: int = 5
    skip_permissions: bool = True

    # Streaming chunks back to gateway via Redis pub/sub. Same Redis instance the
    # gateway uses. Empty disables streaming (executors still run, but the
    # gateway falls back to its non-streaming completion path).
    redis_url: str = ""

    # opencode serve embedded process. Port 0 picks a free port. The worker
    # spawns one ``opencode serve`` per executor instance and reuses it.
    opencode_serve_host: str = "127.0.0.1"
    opencode_serve_port: int = 0

    model_config = SettingsConfigDict(env_file=".env", env_prefix="BSGATEWAY_", extra="ignore")


settings = WorkerSettings()

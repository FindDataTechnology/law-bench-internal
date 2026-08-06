"""Server configuration loaded from .env.

Pydantic settings for FastAPI server (host, port, CORS origins), OpenAI API
credentials, and database URL. Reviewer configs are loaded separately by
agent.config because nodes import them before the app boots.
"""
from __future__ import annotations

from typing import Any

import anyio
from dotenv import load_dotenv
from pydantic_settings import BaseSettings


load_dotenv()


class ServerConfig(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    api_key_enabled: bool = False
    api_keys: str = ""

    class Config:
        env_prefix = ""
        env_file = ".env"
        case_sensitive = False


config = ServerConfig()


def get_server_config() -> ServerConfig:
    return config


# Expose review / quiz models for nodes (lazy import from agent.config)
def _ensure_models():
    """Load reviewer + quiz configs at server startup."""
    from . import config as _cfg
    _cfg._reviewers = None


async def start_models() -> None:
    await anyio.to_thread.run_sync(_ensure_models)


def _setup_api_routes(app: Any) -> None:
    """Register HTTP routers on the FastAPI app after it's created."""
    from fastapi import APIRouter

    from .routes import agent_runs, health

    router = APIRouter()
    router.include_router(health.router, prefix="/", tags=["Health"])
    router.include_router(agent_runs.router, prefix="/", tags=["Agent Runs"])
    app.include_router(router, prefix="/api")

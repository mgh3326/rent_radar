"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.taskiq_app.broker import broker


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize and close Taskiq broker for API process only."""

    if not broker.is_worker_process:
        await broker.startup()
    yield
    if not broker.is_worker_process:
        await broker.shutdown()


app = FastAPI(title="rent-radar", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Basic health endpoint."""

    return {"status": "ok"}

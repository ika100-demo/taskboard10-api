"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from postgres_harness import PostgresServer, free_port

from taskboard10_api.main import app


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)


@pytest.fixture(scope="session")
def postgres(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PostgresServer]:
    """A running throwaway Postgres, stopped at the end of the session."""
    server = PostgresServer(Path(tmp_path_factory.mktemp("pg")))
    server.start()
    try:
        yield server
    finally:
        if server.running:
            server.stop()


@pytest.fixture()
def database_url(postgres: PostgresServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """URL of a fresh empty database, also set as DATABASE_URL."""
    if not postgres.running:
        postgres.start()
    url = postgres.create_database()
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    if not postgres.running:
        postgres.start()


@pytest.fixture()
def unreachable_database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """A database URL on a port nobody listens on, set as DATABASE_URL."""
    url = f"postgresql://postgres@127.0.0.1:{free_port()}/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    return url

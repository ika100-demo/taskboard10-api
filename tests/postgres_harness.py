"""A throwaway Postgres server that tests can stop and restart."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess  # nosec B404
import uuid
from pathlib import Path

import pytest

_TIMEOUT = 60
_PG_ENV_VARS = ("PGHOST", "PGPORT", "PGDATA", "PGUSER", "PGDATABASE")


def free_port() -> int:
    """Return a TCP port on 127.0.0.1 that nobody listens on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _PG_ENV_VARS}


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        args,
        check=check,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        env=_env(),
    )


class PostgresServer:
    """A local Postgres with trust auth on 127.0.0.1 only and no Unix socket."""

    def __init__(self, base_dir: Path) -> None:
        if shutil.which("initdb") is None:
            pytest.fail(
                "initdb not on PATH: run the tests through devbox run test "
                "(devbox.json provides postgresql)"
            )
        self.base_dir = base_dir
        self.data = base_dir / "data"
        self.log = base_dir / "pg.log"
        self.port = free_port()
        _run(
            [
                "initdb",
                "-D",
                str(self.data),
                "-U",
                "postgres",
                "--auth=trust",
                "--no-locale",
                "-E",
                "UTF8",
            ]
        )

    def start(self) -> None:
        options = (
            f"-c listen_addresses=127.0.0.1 -c port={self.port} "
            "-c unix_socket_directories='' -c fsync=off"
        )
        _run(
            [
                "pg_ctl",
                "-D",
                str(self.data),
                "-l",
                str(self.log),
                "-w",
                "-t",
                "30",
                "-o",
                options,
                "start",
            ]
        )

    def stop(self) -> None:
        _run(["pg_ctl", "-D", str(self.data), "-w", "-m", "fast", "stop"])

    @property
    def running(self) -> bool:
        return _run(["pg_ctl", "-D", str(self.data), "status"], check=False).returncode == 0

    def url(self, dbname: str = "postgres") -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/{dbname}"

    def create_database(self) -> str:
        name = f"t_{uuid.uuid4().hex}"
        _run(["createdb", "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", name])
        return self.url(name)

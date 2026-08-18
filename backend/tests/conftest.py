"""Shared fixtures for backend integration tests."""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 — register mapped tables on Base.metadata
from app.config import settings
from app.db.database import Base

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logging.getLogger("fixture_http").debug("%s - %s", self.address_string(), format % args)


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    """Isolated SQLite DB + faster crawler settings for each test."""
    db_path = tmp_path / "test_audit.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(settings, "CRAWLER_REQUEST_DELAY", 0.0)
    monkeypatch.setattr(settings, "CRAWLER_FLUSH_INTERVAL", 0.5)
    monkeypatch.setattr(settings, "ENABLE_PAGESPEED", False)

    yield factory

    engine.dispose()


@pytest.fixture
def fixture_site_no_robots() -> Iterator[str]:
    """Serve the 3-page fixture (no robots.txt) and yield its base URL."""
    root = FIXTURES_DIR / "site_no_robots"
    assert root.is_dir(), f"Missing fixture directory: {root}"
    assert not (root / "robots.txt").exists()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    handler = partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

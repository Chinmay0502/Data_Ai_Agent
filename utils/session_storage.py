
import asyncio
import re
import shutil
import tempfile
import time
from contextvars import ContextVar
from pathlib import Path

STORAGE_ROOT = Path(tempfile.gettempdir()) / "ola_data_agent"
INACTIVITY_SECONDS = 30 * 60
CLEANUP_INTERVAL_SECONDS = 60

current_session_id = ContextVar("current_session_id", default=None)


def validate_session_id(session_id: str) -> str:
    if not session_id or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,100}", session_id
    ):
        raise ValueError("Invalid session ID")
    return session_id


def get_session_folder(session_id=None) -> Path:
    if session_id is None:
        session_id = current_session_id.get()

    session_id = validate_session_id(session_id)
    folder = STORAGE_ROOT / session_id
    folder.mkdir(parents=True, exist_ok=True)

    (folder / ".activity").touch()
    return folder


def get_output_path(relative_path: str, session_id=None) -> Path:
    folder = get_session_folder(session_id)

    # Treat requested output paths as relative to this session.
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ValueError("Absolute output paths are not allowed")

    target = (folder / relative).resolve()
    base = folder.resolve()

    if target != base and base not in target.parents:
        raise ValueError("Output path must stay inside the session folder")

    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def cleanup_expired_sessions() -> int:
    if not STORAGE_ROOT.exists():
        return 0

    now = time.time()
    deleted = 0

    for folder in STORAGE_ROOT.iterdir():
        if not folder.is_dir():
            continue

        marker = folder / ".activity"
        last_activity = (
            marker.stat().st_mtime
            if marker.exists()
            else folder.stat().st_mtime
        )

        if now - last_activity >= INACTIVITY_SECONDS:
            shutil.rmtree(folder, ignore_errors=True)
            deleted += 1

    return deleted


async def cleanup_loop():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        cleanup_expired_sessions()
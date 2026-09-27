import os
from pathlib import Path
from app.core.logging import get_logger

logger = get_logger(__name__)

SESSIONS_DIR = Path("sessions")


def ensure_sessions_dir() -> None:
    SESSIONS_DIR.mkdir(exist_ok=True)


def get_session_path(phone: str) -> str:
    ensure_sessions_dir()
    safe_phone = phone.replace("+", "").replace(" ", "")
    return str(SESSIONS_DIR / f"{safe_phone}.session")


def session_exists(phone: str) -> bool:
    path = get_session_path(phone)
    return os.path.exists(path)


def delete_session(phone: str) -> None:
    path = get_session_path(phone)
    if os.path.exists(path):
        os.remove(path)
        logger.info("session_deleted", phone=phone)

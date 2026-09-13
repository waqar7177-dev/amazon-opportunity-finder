"""Runtime configuration, read from environment variables (and an optional .env).

Nothing here is a secret. SECRET_KEY comes from the environment, or is generated
once per install and kept in the data folder — it is never hard-coded.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

try:  # python-dotenv is a runtime dependency, but the app should still start without it.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent

if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _secret_key(data_dir: Path) -> str:
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    key_file = data_dir / "secret_key"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:  # pragma: no cover - Windows ignores POSIX modes
        pass
    return key


class Config:
    """Settings for a normal local run."""

    def __init__(self, **overrides):
        data_dir = Path(os.environ.get("AOF_DATA_DIR", "").strip() or BASE_DIR / "data")
        self.DATA_DIR = Path(overrides.pop("DATA_DIR", data_dir))
        self.HOST = os.environ.get("AOF_HOST", "127.0.0.1").strip() or "127.0.0.1"
        self.PORT = _int("AOF_PORT", 8877)
        self.OPEN_BROWSER = _bool("AOF_OPEN_BROWSER", True)
        extra_hosts = [h.strip().lower() for h in os.environ.get("AOF_ALLOWED_HOSTS", "").split(",") if h.strip()]
        self.ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"} | set(extra_hosts)
        self.KEEPA_API_KEY = os.environ.get("KEEPA_API_KEY", "").strip()
        self.ENABLE_KEEPA = _bool("AOF_ENABLE_KEEPA", False)

        self.TESTING = False
        self.CSRF_ENABLED = True
        self.MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # uploads: 10 MB
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        self.SECRET_KEY = overrides.pop("SECRET_KEY", None) or _secret_key(self.DATA_DIR)

        for key, value in overrides.items():
            setattr(self, key, value)

    @property
    def DATABASE_PATH(self) -> Path:
        return self.DATA_DIR / "opportunity_finder.db"

    @property
    def LOG_DIR(self) -> Path:
        return self.DATA_DIR / "logs"

    @property
    def BACKUP_DIR(self) -> Path:
        return self.DATA_DIR / "backups"

    @property
    def IMPORT_DIR(self) -> Path:
        return self.DATA_DIR / "imports"

    def as_flask_mapping(self) -> dict:
        return {k: getattr(self, k) for k in dir(self) if k.isupper()}

"""Database backup and restore (SQLite online backup API — safe while the app is running)."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from ..database.db import init_db, looks_like_our_database

MAX_BACKUP_BYTES = 200 * 1024 * 1024


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_backup(db_path: Path, backup_dir: Path, label: str = "backup") -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"opportunity-finder-{label}-{_stamp()}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def restore_backup(data: bytes, db_path: Path, backup_dir: Path) -> tuple[bool, str, Path | None]:
    """Validate an uploaded backup, keep a safety copy of the current data, then restore.

    Returns (ok, message, safety_backup_path)."""
    if not data:
        return False, "The uploaded file is empty.", None
    if len(data) > MAX_BACKUP_BYTES:
        return False, "That file is too large to be a backup of this app.", None
    if not data.startswith(b"SQLite format 3\x00"):
        return False, "That file is not an Opportunity Finder backup (.db).", None
    backup_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db", dir=backup_dir) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        ok, message = looks_like_our_database(tmp_path)
        if not ok:
            return False, message, None
        safety = create_backup(db_path, backup_dir, label="before-restore") if db_path.exists() else None
        src = sqlite3.connect(str(tmp_path))
        dst = sqlite3.connect(str(db_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        init_db(db_path)  # apply any migrations to an older backup
        return True, "Backup restored.", safety
    finally:
        tmp_path.unlink(missing_ok=True)

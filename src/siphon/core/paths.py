"""Backward-compatible user-data and portable-state paths."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil

from siphon.metadata import PRODUCT_NAME


WATCH_STATE_DIR = ".siphon-watcher"
LEGACY_PRODUCT_DIRS = (
)
LEGACY_WATCH_STATE_DIRS = (
)


@dataclass(frozen=True)
class MigrationReport:
    copied_files: int = 0
    skipped_files: int = 0
    skipped_links: int = 0


def migrate_directory(source: Path | str, destination: Path | str) -> MigrationReport:
    """Copy missing files into *destination* without deleting either tree.

    Existing destination files always win.  Symlinks are ignored so migration
    never follows a legacy link outside the user-data directory.
    """
    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_dir():
        return MigrationReport()

    copied = 0
    skipped = 0
    skipped_links = 0
    destination_path.mkdir(parents=True, exist_ok=True)
    for item in sorted(source_path.rglob("*")):
        if item.is_symlink():
            skipped_links += 1
            continue
        relative = item.relative_to(source_path)
        target = destination_path / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file():
            continue
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied += 1
    return MigrationReport(copied, skipped, skipped_links)


def appdata_root(appdata: Path | str | None = None) -> Path:
    if appdata is not None:
        return Path(appdata)
    value = os.environ.get("APPDATA")
    return Path(value) if value else Path.home()


# Folders whose contents have already been brought over in this run.  The
# search for an older install walks whole directory trees, and this path is
# asked for on every settings read, so it must happen once — not thousands of
# times a minute.
_MIGRATED: set[str] = set()


def product_data_dir(
        appdata: Path | str | None = None, *, migrate: bool = True) -> Path:
    root = appdata_root(appdata)
    current = root / PRODUCT_NAME
    if migrate and str(current) not in _MIGRATED:
        _MIGRATED.add(str(current))
        for legacy_name in LEGACY_PRODUCT_DIRS:
            migrate_directory(root / legacy_name, current)
    return current


def select_portable_state_dir(app_dir: Path | str) -> Path:
    root = Path(app_dir)
    current = root / WATCH_STATE_DIR
    for legacy_name in LEGACY_WATCH_STATE_DIRS:
        migrate_directory(root / legacy_name, current)
    return current

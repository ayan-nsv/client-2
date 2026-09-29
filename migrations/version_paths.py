"""Resolve Alembic version_locations from directories that exist on disk.

A client tree may contain only ``core`` + paid products. Listing every product in
``alembic.ini`` would then fail when those folders are absent. Callers set
``version_locations`` from this helper instead.
"""

from __future__ import annotations

from pathlib import Path

# Always present in any valid tree.
REQUIRED_VERSION_DIRS = (
    "migrations/versions",
    "migrations/versions/core",
)

# Optional product branches — included only when the directory exists.
OPTIONAL_PRODUCT_VERSION_DIRS = (
    "market_planner",
    "knowledge",
    "telephone_agent",
)


def shipped_version_locations(root: Path | None = None) -> str:
    """Space-separated ``version_locations`` for products present under ``root``."""
    base = root if root is not None else Path.cwd()
    locations = list(REQUIRED_VERSION_DIRS)
    for name in OPTIONAL_PRODUCT_VERSION_DIRS:
        if (base / "migrations" / "versions" / name).is_dir():
            locations.append(f"migrations/versions/{name}")
    return " ".join(locations)


def apply_shipped_version_locations(config, root: Path | None = None) -> str:
    """Write discovered locations onto an Alembic ``Config`` and return them."""
    if root is None and getattr(config, "config_file_name", None):
        root = Path(config.config_file_name).resolve().parent
    locations = shipped_version_locations(root)
    config.set_main_option("version_locations", locations)
    return locations

#!/usr/bin/env python3
"""Remove unpaid product packages from a client image build.

Used by the Dockerfile after ``COPY . /app/`` when ``INSTALL_PRODUCTS`` is set:

    INSTALL_PRODUCTS=core,market_planner

Always keeps ``core`` (and shared/root). Deletes other product code trees and their
Alembic version directories, then rewrites ``alembic.ini`` ``version_locations`` so
missing dirs are not referenced.

Empty / unset ``INSTALL_PRODUCTS`` is a no-op (full catalogue ships).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# Product name -> paths relative to the app root that belong only to that product.
PRODUCT_PATHS: dict[str, tuple[str, ...]] = {
    "market_planner": (
        "products/market_planner",
        "migrations/versions/market_planner",
    ),
    "knowledge": (
        "products/knowledge",
        "migrations/versions/knowledge",
        # RAG URL scraping imports holdflight.src.scraping.scan
        "holdflight",
    ),
    "telephone_agent": (
        "products/telephone_agent",
        "migrations/versions/telephone_agent",
    ),
}

CORE = "core"
ALEMBIC_INI = "alembic.ini"
VERSION_LOCATIONS_RE = re.compile(
    r"^(version_locations\s*=\s*)(.+)$",
    re.MULTILINE,
)


def _parse_wanted(raw: str) -> set[str]:
    wanted = {p.strip() for p in raw.split(",") if p.strip()}
    wanted.add(CORE)
    unknown = wanted - {CORE} - set(PRODUCT_PATHS)
    if unknown:
        raise SystemExit(
            f"INSTALL_PRODUCTS names unknown product(s): {', '.join(sorted(unknown))}. "
            f"Known optional: {', '.join(sorted(PRODUCT_PATHS))}"
        )
    return wanted


def _rewrite_alembic_ini(root: Path, kept_optional: set[str]) -> None:
    ini_path = root / ALEMBIC_INI
    if not ini_path.is_file():
        return

    locations = ["migrations/versions", "migrations/versions/core"]
    for name in ("market_planner", "knowledge", "telephone_agent"):
        if name in kept_optional:
            locations.append(f"migrations/versions/{name}")

    text = ini_path.read_text(encoding="utf-8")
    replacement = r"\1" + " ".join(locations)
    new_text, count = VERSION_LOCATIONS_RE.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"Could not rewrite version_locations in {ini_path}")
    ini_path.write_text(new_text, encoding="utf-8")
    print(f"alembic.ini version_locations -> {' '.join(locations)}")


def main() -> int:
    raw = (os.environ.get("INSTALL_PRODUCTS") or "").strip()
    if not raw:
        print("INSTALL_PRODUCTS unset; keeping all product packages.")
        return 0

    root = Path(os.environ.get("APP_ROOT") or "/app")
    if not root.is_dir():
        root = Path(__file__).resolve().parents[1]

    wanted = _parse_wanted(raw)
    print(f"Shipping products: {', '.join(sorted(wanted))}")

    for name, paths in PRODUCT_PATHS.items():
        if name in wanted:
            continue
        for rel in paths:
            target = root / rel
            if target.exists():
                shutil.rmtree(target)
                print(f"Removed {rel}")

    _rewrite_alembic_ini(root, wanted & set(PRODUCT_PATHS))
    return 0


if __name__ == "__main__":
    sys.exit(main())

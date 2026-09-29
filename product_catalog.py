"""The set of products this build ships, and the version each one declares.

Lives at the repo root rather than under ``core/`` on purpose. ``core`` must not
import ``products.*`` — that is the dependency inversion the modular architecture
exists to avoid. The repo root is the composition root and is already allowed to
know about every product.

Optional products are imported only when their package is present on disk. A client
image built with ``INSTALL_PRODUCTS=core,market_planner`` can omit unpaid product
trees; this catalogue then contains only what the image actually ships.

The *table* that records installations still lives in the ``core`` schema
(``core.tables.product_tables``). Only this catalogue — "what does the code ship" —
sits outside core.

Adding a product means adding an entry to ``OPTIONAL_PRODUCT_MODULES`` below and
shipping its package. The version itself is owned by the product, declared as
``PRODUCT_VERSION`` in that module.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from types import ModuleType
from typing import NamedTuple

from core import module as core_module

logger = logging.getLogger("marketing-app")

# PRODUCT_NAME -> import path of that product's module.py. Order is registration order.
OPTIONAL_PRODUCT_MODULES: dict[str, str] = {
    "market_planner": "products.market_planner.module",
    "knowledge": "products.knowledge.module",
    "telephone_agent": "products.telephone_agent.vapi.module",
}

# Celery worker contribution modules, keyed by PRODUCT_NAME.
OPTIONAL_WORKER_MODULES: dict[str, str] = {
    "market_planner": "products.market_planner.workers.celery_app",
    "telephone_agent": "products.telephone_agent.vapi.workers.celery_app",
}


class ProductDescriptor(NamedTuple):
    """What the code knows about a product, before consulting the database."""

    name: str
    version: str
    schema: str
    # core owns users/companies and the installed_products table itself, so it can
    # never be uninstalled or disabled. Everything else is optional.
    required: bool = False


def _describe(module: ModuleType, required: bool = False) -> ProductDescriptor:
    return ProductDescriptor(
        name=module.PRODUCT_NAME,
        version=module.PRODUCT_VERSION,
        schema=module.PRODUCT_SCHEMA,
        required=required,
    )


def try_import_module(module_path: str) -> ModuleType | None:
    """Import ``module_path``, or return None if that package is not in this build."""
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        # Only treat this module (or a parent package) as missing. A broken
        # *dependency* inside an installed product should still surface.
        missing = getattr(exc, "name", None) or ""
        parts = module_path.split(".")
        prefixes = {".".join(parts[:i]) for i in range(1, len(parts) + 1)}
        if missing in prefixes:
            logger.info("Product module %s not in this build; skipping", module_path)
            return None
        raise


def module_available(module_path: str) -> bool:
    """Whether ``module_path`` exists in this build, without executing it.

    Presence checks must not import a product's ``module.py``: that pulls in its
    routers and services, and those import the root ``celery_app``. Anything called
    while ``celery_app`` itself is still initialising would then hit a circular
    import.
    """
    try:
        return importlib.util.find_spec(module_path) is not None
    except ModuleNotFoundError:
        return False


def load_optional_product_modules() -> tuple[ModuleType, ...]:
    """Optional product modules that exist in this build, in registration order."""
    loaded: list[ModuleType] = []
    for path in OPTIONAL_PRODUCT_MODULES.values():
        module = try_import_module(path)
        if module is not None:
            loaded.append(module)
    return tuple(loaded)


def load_optional_worker_modules() -> dict[str, ModuleType]:
    """PRODUCT_NAME -> workers.celery_app module for products present in this build."""
    loaded: dict[str, ModuleType] = {}
    for product_name, path in OPTIONAL_WORKER_MODULES.items():
        module = try_import_module(path)
        if module is not None:
            loaded[product_name] = module
    return loaded


def _build_catalog() -> tuple[ProductDescriptor, ...]:
    descriptors: list[ProductDescriptor] = [_describe(core_module, required=True)]
    for module in load_optional_product_modules():
        descriptors.append(_describe(module))
    return tuple(descriptors)


# Built on first use, not at import. Building it imports every product's module.py,
# which imports the root celery_app; doing that at import time makes celery_app and
# this module a cycle.
_catalog_cache: tuple[ProductDescriptor, ...] | None = None


def get_catalog() -> tuple[ProductDescriptor, ...]:
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = _build_catalog()
    return _catalog_cache


def get_descriptor(product_name: str) -> ProductDescriptor | None:
    for descriptor in get_catalog():
        if descriptor.name == product_name:
            return descriptor
    return None


def shipped_product_names() -> frozenset[str]:
    """Names of products whose code is present in this build (including core).

    Answered from module presence alone so callers that only need names — the
    installer, for one — do not pay for importing every product.
    """
    shipped = {core_module.PRODUCT_NAME}
    shipped.update(
        name
        for name, path in OPTIONAL_PRODUCT_MODULES.items()
        if module_available(path)
    )
    return frozenset(shipped)

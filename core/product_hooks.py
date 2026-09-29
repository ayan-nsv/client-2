"""Extension points products use to attach behaviour to core lifecycle events.

Core owns companies, but products need to react when one is created — market_planner
seeds a channel config, and so on. Before this module, core did that by importing
``products.market_planner.tables`` directly, which meant core could not run without
market_planner installed and every new product edited a core file.

Core now calls the hooks and never learns what they do. It does not import products;
products register themselves.

Two registries:

``company_created``
    Runs inside the caller's transaction, per company. A hook receives a flushed
    Company (``company.id`` is populated) and must ``db.add(...)`` **without
    committing** — core owns the transaction boundary and commits once. A hook that
    raises rolls the whole company creation back, which is the pre-existing
    behaviour and is intentional: a company with half its configuration is worse
    than no company.

``backfill``
    Runs once at startup, deployment-wide. Covers companies that already existed
    when a product was switched on, which the per-company hook cannot reach.
    Hooks must be idempotent — startup runs them on every boot.

``startup``
    Runs once per process while the app starts. Covers product-specific work the
    composition root cannot describe on its own — validating an env var only that
    product needs, starting a background loop it owns. Hooks may be sync or async.

    Unlike ``backfill`` these are *not* contained: an exception aborts startup. A
    hook whose failure should only degrade the product rather than block the boot
    has to catch its own errors, because core cannot tell the two cases apart.

``billing_usage``
    Read-only. A product contributes billable quantities for a company over a
    period, returned as a ``{metric_name: number}`` dict which core sums per key.

Registration timing differs by registry, and the difference matters:

*Writing* hooks (company_created, backfill, startup) register inside each product's
``register_*`` function. ``main.py`` imports every product module regardless of
whether it is enabled, so import-time registration would seed tables for products
that are switched off — or, for startup hooks, run a disabled product's background
loop.

*Reading* providers (billing_usage) register at import time instead, because they
must also work in Celery workers, which never call ``register_*``. Registering a
read-only provider for a disabled product is harmless — it queries tables with no
rows and contributes zero — whereas failing to register one produces a silently
wrong bill, which is far worse than a redundant query.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, List

from shared.logger.log import setup_logger

logger = setup_logger("marketing-app")

# (db: Session, company: Company) -> None
CompanyCreatedHook = Callable[..., None]
# (db: Session, company_id: int, data) -> None
CompanyConfigUpdatedHook = Callable[..., None]
# (db: Session) -> None
BackfillHook = Callable[..., None]
# () -> None | Awaitable[None]
StartupHook = Callable[[], Any]
# (db: Session, company_id: int, start_dt_utc, end_dt_utc) -> dict[str, float]
BillingUsageProvider = Callable[..., dict]

_company_created_hooks: List[CompanyCreatedHook] = []
_company_config_updated_hooks: List[CompanyConfigUpdatedHook] = []
_backfill_hooks: List[BackfillHook] = []
_startup_hooks: List[StartupHook] = []
_billing_usage_providers: List[BillingUsageProvider] = []


def register_company_created_hook(hook: CompanyCreatedHook) -> None:
    """Register a hook run inside the transaction that creates a company.

    Idempotent by function identity: ``create_app()`` can run more than once in a
    process (tests, ASGI reloaders) and a product must not seed twice as a result.
    """
    if hook in _company_created_hooks:
        return
    _company_created_hooks.append(hook)


def register_company_config_updated_hook(hook: CompanyConfigUpdatedHook) -> None:
    """Register a hook run when a company's notification config changes.

    Runs inside the caller's transaction, before commit, with the same request
    payload core applied to its own CompanyConfig. Products use it to mirror the
    fields they duplicate. Same idempotency rule as above.
    """
    if hook in _company_config_updated_hooks:
        return
    _company_config_updated_hooks.append(hook)


def register_backfill_hook(hook: BackfillHook) -> None:
    """Register a hook run once at startup. Same idempotency rule as above."""
    if hook in _backfill_hooks:
        return
    _backfill_hooks.append(hook)


def register_startup_hook(hook: StartupHook) -> None:
    """Register a hook run once while the app starts. Same idempotency rule as above.

    Takes no arguments: a hook that needs a database session or an event loop can
    open its own, and keeping the signature empty means core never has to hand a
    product a resource whose lifetime core would then have to manage.
    """
    if hook in _startup_hooks:
        return
    _startup_hooks.append(hook)


def register_billing_usage_provider(provider: BillingUsageProvider) -> None:
    """Register a read-only billable-usage provider. Same idempotency rule as above."""
    if provider in _billing_usage_providers:
        return
    _billing_usage_providers.append(provider)


def collect_billing_usage(db, company_id, start_dt_utc, end_dt_utc) -> dict:
    """Merge every product's billable usage for a company over a period.

    Values under the same key are summed, so two products both reporting
    ``call_seconds`` add up rather than one overwriting the other.

    Exceptions propagate. A provider that fails must not be silently treated as
    zero usage — that would under-bill without any signal that it happened.
    """
    totals: dict = {}
    for provider in _billing_usage_providers:
        for metric, value in provider(db, company_id, start_dt_utc, end_dt_utc).items():
            totals[metric] = totals.get(metric, 0) + value
    return totals


def run_company_created_hooks(db, company) -> None:
    """Invoke every company-created hook. Exceptions propagate to the caller."""
    for hook in _company_created_hooks:
        hook(db, company)


def run_company_config_updated_hooks(db, company_id, data) -> None:
    """Invoke every config-updated hook. Exceptions propagate to the caller.

    Deliberately not contained: these mirror fields the products duplicate, and a
    half-applied update leaving two rows disagreeing is worse than a failed request.
    """
    for hook in _company_config_updated_hooks:
        hook(db, company_id, data)


def run_backfill_hooks(db) -> None:
    """Invoke every backfill hook.

    Unlike company-created hooks these are isolated: one product's backfill failing
    must not stop the others, and must not take down startup. The failure is logged
    and the next hook runs.
    """
    for hook in _backfill_hooks:
        try:
            hook(db)
        except Exception as exc:
            logger.error(
                "Backfill hook %s failed: %s",
                getattr(hook, "__qualname__", hook),
                exc,
            )
            db.rollback()


async def run_startup_hooks() -> None:
    """Invoke every startup hook, awaiting the async ones. Exceptions propagate.

    Fail-fast is the default because the checks that belong here are the ones a
    product cannot run without — serving traffic that is guaranteed to error is
    worse than refusing to boot. Hooks that only want to warn contain themselves.
    """
    for hook in _startup_hooks:
        result = hook()
        if inspect.isawaitable(result):
            await result


def clear_hooks() -> None:
    """Drop all registrations. For tests that build several apps in one process."""
    _company_created_hooks.clear()
    _company_config_updated_hooks.clear()
    _backfill_hooks.clear()
    _startup_hooks.clear()
    _billing_usage_providers.clear()

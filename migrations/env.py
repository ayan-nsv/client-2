"""Alembic environment for the project.

The connection URL and the application schemas come from
``shared.database.postgres.database_config``, so migrations resolve their target the
same way the running app does instead of keeping a second copy of that precedence.

Autogenerate only sees tables that are attached to ``Base.metadata``, which happens as
a side effect of importing the module that declares them. That import list lives in
``shared.database.postgres.model_registry``; a new table file must be added there or
its table will be silently missing from generated revisions.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.operations import ops as alembic_ops
from sqlalchemy import engine_from_config, inspect, pool

from migrations.version_paths import apply_shipped_version_locations
from shared.database.postgres.database_config import (
    APP_SCHEMAS,
    Base,
    resolve_database_url,
)
from shared.database.postgres.model_registry import import_all_models

import_all_models()

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which silently switches off every
    # logger already configured — including the app's "marketing-app". migrate.py runs
    # several upgrades in one process, so without this only the first one's log lines
    # survive and everything after it goes quiet.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Only scan migration branches whose directories exist (subset client trees).
apply_shipped_version_locations(config)

config.set_main_option("sqlalchemy.url", resolve_database_url())

target_metadata = Base.metadata

# Each product owns exactly one schema, so scoping a revision to a product means
# scoping it to that schema.
PRODUCT_SCHEMAS = {
    "core": "core",
    "knowledge": "knowledge",
    "market_planner": "market_planner",
    "telephone_agent": "telephone_agent",
}


def _target_product() -> str | None:
    """The product this run is scoped to, from ``-x product=<name>``.

    Autogenerate compares the whole of ``Base.metadata`` against the whole database
    and has no idea which branch the new revision is going onto. Without this, running

        alembic revision --autogenerate --head market_planner@head

    against a database missing, say, a telephone_agent column would write that change
    into the market_planner branch. Passing ``-x product=market_planner`` narrows both
    sides of the comparison to that product's schema.
    """
    product = context.get_x_argument(as_dictionary=True).get("product")
    if product is None:
        return None
    if product not in PRODUCT_SCHEMAS:
        raise ValueError(
            f"Unknown product {product!r}. Expected one of: "
            f"{', '.join(sorted(PRODUCT_SCHEMAS))}"
        )
    return product


TARGET_PRODUCT = _target_product()
TARGET_SCHEMA = PRODUCT_SCHEMAS[TARGET_PRODUCT] if TARGET_PRODUCT else None


def include_name(name, type_, parent_names) -> bool:
    """Keep autogenerate scoped to the application schemas, or to one product's.

    ``include_schemas=True`` otherwise reflects every schema in the database and would
    propose dropping anything it finds outside the model metadata, ``public`` included.
    """
    if type_ == "schema":
        if TARGET_SCHEMA is not None:
            return name == TARGET_SCHEMA
        return name in APP_SCHEMAS
    return True


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Filter the metadata side to match ``include_name``'s filtering of the database.

    ``include_name`` governs what is reflected out of the database; without the same
    cut applied to the model metadata, a product-scoped run would still see every
    other product's tables as "missing" and emit CREATE TABLE for them.
    """
    if TARGET_SCHEMA is None:
        return True
    if type_ == "table":
        return obj.schema == TARGET_SCHEMA
    parent = getattr(obj, "table", None)
    if parent is not None:
        return parent.schema == TARGET_SCHEMA
    return True


def render_item(type_, obj, autogen_context) -> bool:
    """Emit the import that pgvector column types need.

    Autogenerate renders these as ``pgvector.sqlalchemy.vector.VECTOR(...)`` but does
    not add the corresponding import, so the revision fails with a NameError at runtime.
    """
    if type_ == "type" and type(obj).__module__.startswith("pgvector."):
        autogen_context.imports.add("import pgvector.sqlalchemy.vector")
        return False
    return False


def _creates_tables_in_schema(upgrade_ops, schema: str) -> bool:
    return any(
        isinstance(op, alembic_ops.CreateTableOp) and op.schema == schema
        for op in upgrade_ops.ops
    )


def process_revision_directives(context, revision, directives) -> None:
    """Inject CREATE SCHEMA when autogenerate is bootstrapping a product.

    Alembic compares tables and indexes, not PostgreSQL schemas. ``Table.schema``
    only qualifies ``CREATE TABLE core.companies``; it never produces
    ``CREATE SCHEMA``. env.py also must not create schemas at migrate time — a
    telephone-only install should not get empty market_planner/knowledge schemas.
    The first revision for a product therefore owns ``CREATE SCHEMA``.

    This hook writes that line (and knowledge's ``vector`` extension) when:

    * the run is scoped with ``-x product=...``,
    * the new revision creates tables in that product's schema, and
    * the database does not already have the schema.

    Later revisions against an existing schema are left alone, so a downgrade
    does not ``DROP SCHEMA ... CASCADE``.
    """
    if TARGET_SCHEMA is None or not directives:
        return
    script = directives[0]
    upgrade_ops = getattr(script, "upgrade_ops", None)
    if upgrade_ops is None or upgrade_ops.is_empty():
        return
    if not _creates_tables_in_schema(upgrade_ops, TARGET_SCHEMA):
        return

    connection = getattr(context, "connection", None)
    if connection is not None and TARGET_SCHEMA in inspect(connection).get_schema_names():
        return

    upgrade_ops.ops.insert(
        0,
        alembic_ops.ExecuteSQLOp(f'CREATE SCHEMA IF NOT EXISTS "{TARGET_SCHEMA}"'),
    )
    if TARGET_SCHEMA == "knowledge":
        upgrade_ops.ops.insert(
            1,
            alembic_ops.ExecuteSQLOp("CREATE EXTENSION IF NOT EXISTS vector"),
        )
    downgrade_ops = getattr(script, "downgrade_ops", None)
    if downgrade_ops is not None:
        downgrade_ops.ops.append(
            alembic_ops.ExecuteSQLOp(f'DROP SCHEMA IF EXISTS "{TARGET_SCHEMA}" CASCADE')
        )


def run_migrations_offline() -> None:
    context.configure(
        url=resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        render_item=render_item,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Schemas are NOT created here. Each product's initial revision creates its own,
    # which is what lets a deployment install only the products it bought: creating
    # every schema up front would leave empty market_planner/knowledge schemas on a
    # telephone-only install.
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            include_object=include_object,
            compare_type=True,
            render_item=render_item,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

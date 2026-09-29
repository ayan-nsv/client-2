import ipaddress
import logging
import os
from urllib.parse import quote_plus, urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

load_dotenv()

# Singleton pattern for database engine and session
_engine = None
_SessionLocal = None
Base = declarative_base()
_log = logging.getLogger(__name__)

# PostgreSQL schemas used by SQLAlchemy models (__table_args__ = {"schema": ...})
APP_SCHEMAS = ("core", "knowledge", "market_planner", "telephone_agent")


def _warn_if_router_ip_mistake(host: str) -> None:
    """192.168.1.1 is usually the Wi‑Fi router, not a machine running PostgreSQL."""
    h = (host or "").strip()
    if h == "192.168.1.1" and (os.getenv("DOCKER") or "").strip() == "1":
        _log.warning(
            "POSTGRES_HOST is 192.168.1.1 (typically your router). "
            "Use your PC IP or host.docker.internal with POSTGRES_USE_DOCKER_INTERNAL_GATEWAY=1."
        )


def _postgres_host_for_docker_clients(host: str) -> str:
    """
    Inside Docker Desktop, reaching the host PC via a LAN IP (e.g. 192.168.1.6 or 192.168.43.x
    on a phone hotspot) often fails with \"Network is unreachable\".

    Opt-in: DOCKER=1 and POSTGRES_USE_DOCKER_INTERNAL_GATEWAY=1 → rewrites 192.168.0.0/16 to
    host.docker.internal (Postgres must be listening on the host, not only 127.0.0.1).
    """
    if (os.getenv("DOCKER") or "").strip() != "1":
        return host
    if (os.getenv("POSTGRES_USE_DOCKER_INTERNAL_GATEWAY") or "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return host
    h = (host or "").strip()
    if h in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
        return h
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return h
    if ip.version == 4 and ip in ipaddress.ip_network("192.168.0.0/16"):
        _log.info(
            "postgres host rewritten for Docker: %s -> host.docker.internal",
            h,
        )
        return "host.docker.internal"
    return h


def _environment_is_prod() -> bool:
    env = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "").strip().lower()
    return env in ("prod", "production")


def _prod_credentials_complete() -> bool:
    h = (os.getenv("PROD_HOST") or "").strip()
    u = (os.getenv("PROD_USER") or "").strip()
    n = (os.getenv("PROD_DB") or "").strip()
    return bool(h and u and n)


def _require_rds_hostname_not_arn(host: str) -> None:
    """RDS connection strings need the DNS endpoint, not arn:aws:rds:..."""
    h = host.strip()
    if h.lower().startswith("arn:"):
        raise ValueError(
            "PROD_HOST must be the RDS endpoint hostname (e.g. "
            "mydb.abc123xyz.eu-north-1.rds.amazonaws.com), not an ARN. "
            "AWS Console → RDS → your database → Connectivity & security → Endpoint."
        )


def resolve_database_url() -> str:
    """
    Resolve the PostgreSQL connection URL.

    Precedence:
    1. ENVIRONMENT in (prod, production) and PROD_HOST, PROD_USER, PROD_DB set — URL from PROD_*.
    2. POSTGRES_HOST, POSTGRES_USER, and POSTGRES_DB all non-empty — URL built from POSTGRES_*
       (password from POSTGRES_PASSWORD). This is the normal .env layout; it wins over DATABASE_URL
       so a stale DATABASE_URL cannot override POSTGRES_*.
       With DOCKER=1 and POSTGRES_USE_DOCKER_INTERNAL_GATEWAY=1, 192.168.x.x rewrites to
       host.docker.internal.
    3. DATABASE_URL — if set (non-empty), when the POSTGRES_* triple above is not all set.
    4. Otherwise — built from POSTGRES_* with local defaults (localhost, postgres, market_planner_local).
    """
    if _environment_is_prod() and _prod_credentials_complete():
        host = (os.getenv("PROD_HOST") or "").strip()
        _require_rds_hostname_not_arn(host)
        port = os.getenv("PROD_PORT", "5432")
        user = (os.getenv("PROD_USER") or "").strip()
        password = os.getenv("PROD_PASSWORD") or ""
        name = (os.getenv("PROD_DB") or "").strip()
        u = quote_plus(user)
        p = quote_plus(password)
        return f"postgresql://{u}:{p}@{host}:{port}/{name}"

    pg_host = (os.getenv("POSTGRES_HOST") or "").strip()
    pg_user = (os.getenv("POSTGRES_USER") or "").strip()
    pg_db = (os.getenv("POSTGRES_DB") or "").strip()
    if pg_host and pg_user and pg_db:
        _warn_if_router_ip_mistake(pg_host)
        pg_host = _postgres_host_for_docker_clients(pg_host)
        port = (os.getenv("POSTGRES_PORT") or "5432").strip() or "5432"
        password = os.getenv("POSTGRES_PASSWORD") or ""
        u = quote_plus(pg_user)
        p = quote_plus(password)
        return f"postgresql://{u}:{p}@{pg_host}:{port}/{pg_db}"

    explicit = (os.getenv("DATABASE_URL") or "").strip()
    if explicit:
        return explicit

    if _environment_is_prod():
        raise ValueError(
            "ENVIRONMENT is prod but PROD_HOST, PROD_USER, and PROD_DB must be set "
            "(or set DATABASE_URL)."
        )
    
    raw_host = (os.getenv("POSTGRES_HOST") or "localhost").strip()
    _warn_if_router_ip_mistake(raw_host)
    host = _postgres_host_for_docker_clients(raw_host)
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD") or ""
    name = os.getenv("POSTGRES_DB", "market_planner_local")

    u = quote_plus(user)
    p = quote_plus(password)
    return f"postgresql://{u}:{p}@{host}:{port}/{name}"


def get_database_url():
    """Same as resolve_database_url(); kept for scripts that import this name."""
    return resolve_database_url()


def get_engine():
    """
    Returns a singleton SQLAlchemy engine instance.
    Creates a new engine if one doesn't exist.
    """
    global _engine
    
    if _engine is None:
        database_url = resolve_database_url()
        if (os.getenv("DOCKER") or "").strip() == "1":
            try:
                pu = urlparse(database_url)
                _log.info(
                    "database engine dsn (no password): host=%s port=%s database=%s",
                    pu.hostname,
                    pu.port,
                    (pu.path or "/").lstrip("/").split("?")[0] or "(none)",
                )
            except Exception:
                pass

        # Optimized pooling for EC2/RDS environment
        # Pool sizes are configurable via env vars to match expected concurrency
        _pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
        _max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "20"))
        _pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))
        _statement_timeout = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
        _connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))

        _log.info(
            "database pool config: pool_size=%s max_overflow=%s recycle=%ss",
            _pool_size, _max_overflow, _pool_recycle,
        )

        _engine = create_engine(
            database_url,
            pool_size=_pool_size,
            max_overflow=_max_overflow,
            pool_recycle=_pool_recycle,
            pool_pre_ping=True,    # Check connection health before use
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            connect_args={
                "connect_timeout": _connect_timeout,
                "options": f"-c statement_timeout={_statement_timeout}"
            }
        )
    
    return _engine


def get_session_local():
    """
    Returns a singleton sessionmaker instance.
    Creates a new sessionmaker if one doesn't exist.
    """
    global _SessionLocal
    
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    return _SessionLocal


def get_db():
    """
    Dependency function for FastAPI to get a database session.
    Yields a database session and ensures it's closed after use.
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schemas(engine=None, schemas=None):
    """Create application PostgreSQL schemas if they do not exist.

    ``schemas`` defaults to every schema in APP_SCHEMAS, and callers should leave it
    that way until per-product migration chains exist. Restricting it today would
    break the migration path: ``migrations/env.py`` calls this and then runs a single
    chain that creates tables in all four schemas, so omitting one makes the very next
    CREATE TABLE fail on a missing schema. The parameter is here so that work can pass
    an enabled-product subset without reshaping this function.
    """
    eng = engine or get_engine()
    targets = APP_SCHEMAS if schemas is None else tuple(schemas)
    with eng.begin() as conn:
        for schema in targets:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def init_db():
    """
    Initialize the database by creating all tables.
    Call this after defining your models.
    """
    engine = get_engine()
    ensure_schemas(engine)
    Base.metadata.create_all(bind=engine)


def close_db():
    """
    Close the database engine connection.
    Useful for cleanup during application shutdown.
    """
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None

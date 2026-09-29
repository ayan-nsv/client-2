import asyncio
import json
import os
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# Loaded so task producers (.delay / send_task) publish through the configured app.
from celery_app import celery_app  # noqa: F401

from core.bootstrap import ensure_reference_data
from core.module import register_core
from core.product_gate import get_enabled_product_names
from core.product_hooks import run_backfill_hooks, run_startup_hooks
from product_catalog import load_optional_product_modules

from shared.database.postgres.database_config import get_session_local
from shared.database.postgres.model_registry import import_all_models
from shared.utils.firebase.firebase_config import init_firebase_admin
from shared.logger.log import setup_logger
from shared.utils.error.error_handler import format_http_exception_content
from shared.middleware.cors import setup_cors_middleware

logger = setup_logger("marketing-app")


# Register every shipped model before lifespan DB work or relationship()
# resolution fails.
import_all_models()


class LenientJSONMiddleware:
    """
    Accept lenient JSON such as:
    - single quotes
    - unquoted keys
    - trailing commas

    and normalize it to valid JSON before passing it to route handlers.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        headers_list = scope.get("headers", [])

        headers_dict = {}
        for key, value in headers_list:
            key = (
                key.decode("utf-8").lower()
                if isinstance(key, bytes)
                else key.lower()
            )
            value = (
                value.decode("utf-8", errors="ignore")
                if isinstance(value, bytes)
                else value
            )
            headers_dict[key] = value

        content_type = headers_dict.get("content-type", "")

        if method in ("POST", "PUT", "PATCH") and "application/json" in content_type.lower():

            async def new_receive():
                body_chunks = []
                more_body = True

                while more_body:
                    message = await receive()

                    if message.get("type") != "http.request":
                        return message

                    body_chunks.append(message.get("body", b""))
                    more_body = message.get("more_body", False)

                body = b"".join(body_chunks)

                if not body:
                    return {
                        "type": "http.request",
                        "body": b"",
                        "more_body": False,
                    }

                try:
                    body_str = body.decode(
                        "utf-8",
                        errors="replace",
                    )
                except Exception:
                    return {
                        "type": "http.request",
                        "body": body,
                        "more_body": False,
                    }

                # First try standard JSON.
                try:
                    json.loads(body_str)

                    return {
                        "type": "http.request",
                        "body": body,
                        "more_body": False,
                    }

                except json.JSONDecodeError:
                    pass

                # Then try JSON5.
                try:
                    import json5

                    data = json5.loads(body_str)

                    return {
                        "type": "http.request",
                        "body": json.dumps(data).encode("utf-8"),
                        "more_body": False,
                    }

                except Exception:
                    return {
                        "type": "http.request",
                        "body": body,
                        "more_body": False,
                    }

            await self.app(scope, new_receive, send)

        else:
            await self.app(scope, receive, send)


def _make_errors_json_serializable(errors: list) -> list:
    """
    Convert validation errors to JSON-serializable format.
    """
    result = []

    for error in errors:
        sanitized = {}

        for key, value in error.items():
            if key == "ctx" and isinstance(value, dict):
                sanitized[key] = {
                    ctx_key: (
                        str(ctx_value)
                        if not isinstance(
                            ctx_value,
                            (str, int, float, bool, type(None)),
                        )
                        else ctx_value
                    )
                    for ctx_key, ctx_value in value.items()
                }

            elif isinstance(
                value,
                (str, int, float, bool, type(None), list),
            ):
                sanitized[key] = value

            else:
                sanitized[key] = str(value)

        result.append(sanitized)

    return result


def _configure_threadpool():
    """
    Configure the default asyncio executor used by asyncio.to_thread().
    """
    threadpool_size = int(
        os.getenv("ASYNC_THREADPOOL_SIZE", "40")
    )

    loop = asyncio.get_running_loop()

    loop.set_default_executor(
        ThreadPoolExecutor(
            max_workers=threadpool_size
        )
    )

    logger.info(
        "asyncio threadpool configured: max_workers=%s",
        threadpool_size,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info(
        "Starting Marketing Planner API..."
    )

    # ------------------------------------------------------------------
    # 1. Async threadpool
    # ------------------------------------------------------------------

    _configure_threadpool()

    # ------------------------------------------------------------------
    # 2. Firebase
    # ------------------------------------------------------------------

    try:
        init_firebase_admin()

    except Exception as exc:
        logger.error(
            "Failed to initialize Firebase Admin: %s",
            exc,
        )

    # ------------------------------------------------------------------
    # 3. Database bootstrap
    # ------------------------------------------------------------------

    db = get_session_local()()

    try:
        ensure_reference_data(db)

    except Exception as exc:
        logger.error(
            "Failed to seed core reference data: %s",
            exc,
        )

        # A failed statement leaves the session in an aborted
        # transaction.
        db.rollback()

    # ------------------------------------------------------------------
    # 4. Product backfill hooks
    # ------------------------------------------------------------------

    try:
        run_backfill_hooks(db)

    except Exception as exc:
        logger.error(
            "Failed to run product backfill hooks: %s",
            exc,
        )

    finally:
        db.close()

    # ------------------------------------------------------------------
    # 5. Product startup hooks
    # ------------------------------------------------------------------
    #
    # Only enabled products registered one, since registration happens in their
    # register_* function. Uncontained: a product that declares a startup
    # requirement is entitled to stop the boot when it is not met.

    await run_startup_hooks()

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    logger.info(
        "Shutting down Marketing Planner API..."
    )

    try:
        from shared.cache.redis.redis import close_redis_client

        await close_redis_client()

    except Exception as exc:
        logger.warning(
            "Error during Redis cleanup: %s",
            exc,
        )


def _optional_registrars():
    """
    Return (product_name, register_fn) for optional products
    shipped in this build.
    """

    for module in load_optional_product_modules():

        register = getattr(
            module,
            f"register_{module.PRODUCT_NAME}",
            None,
        )

        if register is None:
            logger.warning(
                "Product %s has no register_%s(); "
                "skipping route registration",
                module.PRODUCT_NAME,
                module.PRODUCT_NAME,
            )
            continue

        yield module.PRODUCT_NAME, register


def create_app() -> FastAPI:

    app = FastAPI(
        title="Marketing Planner API",
        description=(
            "API for managing marketing campaigns "
            "and content generation"
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    setup_cors_middleware(app)

    app.add_middleware(
        LenientJSONMiddleware
    )

    # ------------------------------------------------------------------
    # Core routes
    # ------------------------------------------------------------------

    register_core(app)

    # ------------------------------------------------------------------
    # Optional products
    # ------------------------------------------------------------------

    enabled = get_enabled_product_names()

    for product_name, register in _optional_registrars():

        if product_name in enabled:
            register(app)

        else:
            logger.info(
                "Product %s is disabled; "
                "skipping route registration",
                product_name,
            )

    return app


app = create_app()


# ----------------------------------------------------------------------
# Custom OpenAPI
# ----------------------------------------------------------------------

def _custom_openapi():

    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = schema.setdefault(
        "components",
        {},
    )

    security_schemes = components.setdefault(
        "securitySchemes",
        {},
    )

    security_schemes["FirebaseBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "description": (
            "Firebase ID token "
            "(Authorization: Bearer …)"
        ),
    }

    security_schemes["X-API-KEY"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-KEY",
        "description": (
            "Static service key "
            "(STATIC_API_KEY env var)"
        ),
    }

    security_schemes["X-ADMIN-SECRET"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-ADMIN-SECRET",
        "description": (
            "Admin secret "
            "(ADMIN_SECRET env var)"
        ),
    }

    app.openapi_schema = schema

    return app.openapi_schema


app.openapi = _custom_openapi


# ----------------------------------------------------------------------
# Exception handlers
# ----------------------------------------------------------------------

@app.exception_handler(
    RequestValidationError
)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):

    errors = exc.errors()

    logger.warning(
        "Validation error: %s",
        errors,
    )

    is_json_error = any(
        error.get("type") == "json_invalid"
        for error in errors
    )

    message = (
        "Invalid JSON in request body. "
        "Use JSON.stringify() for the body "
        "and ensure Content-Type is application/json."
        if is_json_error
        else "Validation error"
    )

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": message,
            "errors": _make_errors_json_serializable(
                errors
            ),
            "data": [],
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):

    return JSONResponse(
        status_code=exc.status_code,
        content=format_http_exception_content(
            exc.detail
        ),
    )


@app.exception_handler(
    StarletteHTTPException
)
async def starlette_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):

    return JSONResponse(
        status_code=exc.status_code,
        content=format_http_exception_content(
            exc.detail
        ),
    )


# ----------------------------------------------------------------------
# Static UI Files
# ----------------------------------------------------------------------

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)


@app.get(
    "/qa",
    response_class=HTMLResponse,
    tags=["ui"],
)
async def get_qa_index():
    return FileResponse(
        "static/ui/index.html"
    )


@app.get(
    "/qa/dashboard",
    response_class=HTMLResponse,
    tags=["ui"],
)
async def get_qa_dashboard():
    return FileResponse(
        "static/ui/dashboard.html"
    )


@app.get(
    "/qa/analytics",
    response_class=HTMLResponse,
    tags=["ui"],
)
async def get_qa_analytics():

    html_path = Path(
        "static/ui/analytics.html"
    )

    content = html_path.read_text(
        encoding="utf-8"
    )

    admin_secret_json = json.dumps(
        os.getenv("ADMIN_SECRET") or ""
    )

    content = content.replace(
        "__SERVER_ADMIN_SECRET_JSON__",
        admin_secret_json,
    )

    return HTMLResponse(content)


@app.get(
    "/dictionaries",
    response_class=HTMLResponse,
    tags=["ui"],
)
async def get_dictionaries():
    return FileResponse(
        "static/ui/dictionaries.html"
    )


@app.get(
    "/categories",
    response_class=HTMLResponse,
    tags=["ui"],
)
async def get_categories_admin_ui():
    return FileResponse(
        "static/ui/categories.html"
    )


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------

@app.get("/")
async def root():

    return {
        "message": "Marketing Planner API..",
        "version": "1.0.0",
        "status": "healthy",
    }


@app.get("/health")
async def health_check():

    return {
        "status": "healthy",
        "service": "marketing-planner-api",
    }
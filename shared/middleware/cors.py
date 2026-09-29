"""CORS middleware setup for the FastAPI application."""

from fastapi.middleware.cors import CORSMiddleware

from shared.middleware.cors_config import get_cors_allow_credentials, get_cors_allowed_origins
# from utils.logger import setup_logger

# logger = setup_logger("marketing-app")


def setup_cors_middleware(app) -> None:
    """Register CORS middleware with an explicit origin allowlist from env."""
    allowed_origins = get_cors_allowed_origins()
    allow_credentials = get_cors_allow_credentials()
    if not allowed_origins:
        # logger.warning(
        #     "CORS allowlist is empty (CORS_ALLOWED_ORIGINS unset). "
        #     "Browser cross-origin requests will be blocked until origins are configured."
        # )
        pass
    else:
        # logger.info(
        #     "CORS configured: origins=%s allow_credentials=%s",
        #     allowed_origins,
        #     allow_credentials,
        # )
        pass
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

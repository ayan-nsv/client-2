from fastapi import FastAPI

from products.knowledge.rag.api import chat_routes, chatbot_routes, rag_routes

API_PREFIX = "/api/v1"

# Identity recorded in core.installed_products. Bump PRODUCT_VERSION on release.
PRODUCT_NAME = "knowledge"
PRODUCT_VERSION = "1.0.0"
PRODUCT_SCHEMA = "knowledge"


def register_knowledge(app: FastAPI) -> None:
    app.include_router(rag_routes.router, prefix=API_PREFIX)
    app.include_router(chatbot_routes.router, prefix=API_PREFIX)
    app.include_router(chat_routes.router, prefix=API_PREFIX)

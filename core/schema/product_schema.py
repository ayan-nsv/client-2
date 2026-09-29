"""Pydantic models for the installed-products API."""

from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class InstalledProductResponse(BaseModel):
    id: int
    uuid: Optional[str] = None
    product_name: str
    installed_version: str
    enabled: bool
    install_date: Optional[datetime] = None
    schema_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class InstalledProductUpdateRequest(BaseModel):
    enabled: bool = Field(
        ...,
        description=(
            "Turn the product on or off for this deployment. Disabling stops its "
            "routes and services from loading; it does not drop its schema or data."
        ),
    )

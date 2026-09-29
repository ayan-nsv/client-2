from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CompanyBillingPatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tier: Optional[Literal["FREE", "PAID"]] = None
    agent_category: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("agent_category", "agentCategory"),
    )


class BillingUsageResponse(BaseModel):
    ecoId: str
    overage_minutes: int
    sms_sent: int
    periodStart: str
    periodEnd: str
    agentCategory: Optional[str] = None

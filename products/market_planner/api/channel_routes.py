from fastapi import APIRouter

from fastapi import Depends
from shared.utils.auth import auth
from products.market_planner.services.channel_service import ChannelService
from products.market_planner.schema import channel_schema

# logger = setup_logger("marketing-app")

router = APIRouter()


###################################################### configure channel ##################################################
@router.post("/channel/{company_id}/config", tags=["channel"])
async def configure_channel(company_id: str, request: channel_schema.ChannelConfigRequest, user: dict = Depends(auth.get_current_user)):
    return await ChannelService.configure_channel(company_id, request.model_dump_json(), user)
    


###################################################### get channel config ##################################################
@router.get("/channel/{company_id}/config", tags=["channel"])
async def get_channel_config(company_id: str, user: dict = Depends(auth.get_current_user)):
    return await ChannelService.get_channel_config(company_id, user)
    


@router.put("/channel/{company_id}/config", tags=["channel"])
async def update_channel_config(company_id: str, channel_config: channel_schema.ChannelConfigRequest, user: dict = Depends(auth.get_current_user)):
    return await ChannelService.update_channel_config(company_id, channel_config.model_dump_json(), user)

    
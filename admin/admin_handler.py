# pyrefly: ignore[missing-import]
from aiogram.dispatcher import router
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel
from database.database import db
from config.models import GetPricesBody




router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/get-prices")
async def get_prices(body: GetPricesBody):
    location_id = body.location
    prices = await db.get_prices_by_location(location_id)
    
    resp = {}
    for time_slot_data in prices:
        resp[time_slot_data[2]] = time_slot_data[0]

    return resp




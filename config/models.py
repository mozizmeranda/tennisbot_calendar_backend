from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import date



class FreeSlotsBody(BaseModel):
    location: str = Field(..., description="Локация (напр., 'A' или 'B')", examples=["A"])
    year:     int = Field(..., description="Год",  examples=[2026])
    month:    int = Field(..., ge=1, le=12, description="Месяц (1-12)", examples=[9])
    day:      int = Field(..., ge=1, le=31, description="День (1-31)",  examples=[10])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "location": "A",
                    "year": 2026,
                    "month": 9,
                    "day": 10
                }
            ]
        }
    }


class GetFullPriceBody(BaseModel):
    location: str
    day: str
    telegram_id: Optional[int] = None
    time_slots: Dict[str, int] = Field(..., description="Словарь вида {'10:00-11:00': 2}")


class CancelBookingBody(BaseModel):
    booking_id: str = Field(..., description="ID брони (temporary_order_id), которую нужно отменить")


class PerformBookingBody(BaseModel):
    booking_id: str = Field(..., description="ID брони (temporary_order_id), которую нужно подтвердить")
    number: str


class UpdateProfileBody(BaseModel):
    name: Optional[str] = Field(None, description="Новое имя пользователя")
    phone: Optional[str] = Field(None, description="Новый номер телефона")


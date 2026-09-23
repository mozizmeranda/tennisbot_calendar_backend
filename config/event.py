from pydantic import BaseModel, model_validator
from typing import List, Optional
from datetime import datetime, time, date
from datetime import time as time_type


# Request Schemas
class SingleEventCreate(BaseModel):
    title: str
    start_datetime: datetime
    end_datetime: datetime
    status: str

    @model_validator(mode='after')
    def check_dates(self) -> 'SingleEventCreate':
        if self.start_datetime.tzinfo is not None:
            self.start_datetime = self.start_datetime.replace(tzinfo=None)
        if self.end_datetime.tzinfo is not None:
            self.end_datetime = self.end_datetime.replace(tzinfo=None)

        if self.start_datetime >= self.end_datetime:
            raise ValueError("start_datetime must be before end_datetime")
        if self.status not in ("confirmed", "pending_payment", "cancelled"):
            raise ValueError("Invalid status")
        return self


class SingleEventUpdate(BaseModel):
    title: Optional[str] = None
    start_datetime: datetime
    end_datetime: datetime

    @model_validator(mode='after')
    def check_dates(self) -> 'SingleEventUpdate':
        if self.start_datetime.tzinfo is not None:
            self.start_datetime = self.start_datetime.replace(tzinfo=None)
        if self.end_datetime.tzinfo is not None:
            self.end_datetime = self.end_datetime.replace(tzinfo=None)

        if self.start_datetime >= self.end_datetime:
            raise ValueError("start_datetime must be before end_datetime")
        return self


class RecurringEventCreate(BaseModel):
    title: str
    days_of_week: List[int]
    start_time: time
    end_time: time

    @model_validator(mode='after')
    def check_times(self) -> 'RecurringEventCreate':
        
        midnight = time_type(0, 0, 0)
        # end_time == 00:00:00 означает полночь следующего дня — это валидно для слота 23:00-00:00
        if self.end_time != midnight and self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        for day in self.days_of_week:
            if day < 0 or day > 6:
                raise ValueError("days_of_week must be between 0 (Monday) and 6 (Sunday)")
        return self


class CancelInstanceRequest(BaseModel):
    date: date


# Response Schemas
class SingleEventResponse(BaseModel):
    id: int
    calendar_id: str
    created_by: Optional[int]
    title: str
    start_datetime: datetime
    end_datetime: datetime
    status: str
    recurring_event_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class RecurringEventResponse(BaseModel):
    id: int
    calendar_id: str
    title: str
    day_of_week: int
    start_time: time
    end_time: time

    class Config:
        from_attributes = True



class GridEventResponse(BaseModel):
    id: int
    type: str  # "single" or "recurring_instance"
    title: str
    start_datetime: datetime
    end_datetime: datetime
    status: str
    recurring_event_id: Optional[int]

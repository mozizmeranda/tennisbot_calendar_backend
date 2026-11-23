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
    # Первая дата действия серии (включительно). None = с сегодняшнего дня.
    start_date: Optional[date] = None
    # Последняя дата действия серии (включительно). None = бессрочно.
    end_date: Optional[date] = None

    @model_validator(mode='after')
    def check_times(self) -> 'RecurringEventCreate':
        
        midnight = time_type(0, 0, 0)
        # end_time == 00:00:00 означает полночь следующего дня — это валидно для слота 23:00-00:00
        if self.end_time != midnight and self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        for day in self.days_of_week:
            if day < 0 or day > 6:
                raise ValueError("days_of_week must be between 0 (Monday) and 6 (Sunday)")
        if not self.days_of_week:
            raise ValueError("days_of_week must not be empty")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class ReservationCreate(BaseModel):
    """Закрепление слота за человеком: создаёт одиночные события на каждую подходящую дату периода."""
    title: str
    days_of_week: List[int]
    start_time: time
    end_time: time
    start_date: Optional[date] = None      # None = сегодня
    end_date: Optional[date] = None        # если не задана — start_date + months
    months: int = 1                        # используется, если end_date не задана
    status: str = "confirmed"
    skip_conflicts: bool = False           # True: заполненные даты пропускаются, остальные создаются

    @model_validator(mode='after')
    def check_all(self) -> 'ReservationCreate':
        midnight = time_type(0, 0, 0)
        if self.end_time != midnight and self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if not self.days_of_week:
            raise ValueError("days_of_week must not be empty")
        for day in self.days_of_week:
            if day < 0 or day > 6:
                raise ValueError("days_of_week must be between 0 (Monday) and 6 (Sunday)")
        if self.months < 1 or self.months > 12:
            raise ValueError("months must be between 1 and 12")
        if self.status not in ("confirmed", "pending_payment"):
            raise ValueError("Invalid status")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class InstanceTitleUpdate(BaseModel):
    """Смена названия одного конкретного слота серии (остальная серия не меняется)."""
    date: date
    title: str

    @model_validator(mode='after')
    def check_title(self) -> 'InstanceTitleUpdate':
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title must not be empty")
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
    start_date: Optional[date] = None
    end_date: Optional[date] = None

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

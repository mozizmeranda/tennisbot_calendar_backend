from pydantic import BaseModel
from typing import List


class CalendarBase(BaseModel):
    name: str
    max_events_per_hour: int


class CalendarResponse(CalendarBase):
    id: str

    class Config:
        from_attributes = True


class CreateCalendar(BaseModel):
    id: str
    name: str
    max_events_per_hour: int = 1


class CreateUser(BaseModel):
    telegram_id: int
    username: str
    full_name: str


class CalendarMembers(BaseModel):
    telegram_id: int
    calendar_id: str
    role: str = "trainer"  # 'admin' | 'trainer'


class MigrateGoogleCalendarRequest(BaseModel):
    google_calendar_id: str


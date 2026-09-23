from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from database.database import db

profile_router = APIRouter(prefix="/profile", tags=["Profile"])


@profile_router.get("/{telegram_id}")
async def get_profile(telegram_id: int):
    """
    Получение профиля пользователя и всех его бронирований.
    """
    rows = await db.get_full_profile(telegram_id)

    if not rows:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Пользователь не найден"}
        )

    result = {
        "name": rows[0][0],
        "phone": rows[0][1],
        "bookings": []
    }

    for row in rows:
        if row[2] is not None:
            result["bookings"].append({
                "date": row[3],
                "location": row[2],
                "telegram_id": telegram_id,
                "time_slot": row[4]
            })

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)

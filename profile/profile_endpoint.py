from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from database.database import db
from config import models

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
        "name": rows['profile'][0],
        "phone": rows['profile'][1],
        "bookings": []
    }
    print(f"BOOKINGS: {rows["future_bookings"]}")
    for row in rows["future_bookings"]:
        result["bookings"].append({
                "date": row[1],
                "location": row[0],
                "telegram_id": telegram_id,
                "time_slot": row[2]
            })

    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


@profile_router.put("/{telegram_id}")
async def update_profile(telegram_id: int, body: models.UpdateProfileBody):
    """
    Изменение имени и номера телефона пользователя.
    """
    # Проверяем, существует ли пользователь (опираясь на то, что если нет профиля - нет юзера)
    rows = await db.get_full_profile(telegram_id)
    if not rows:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Пользователь не найден"}
        )

    try:
        await db.update_user_profile(telegram_id, body.name, body.phone)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "success", "message": "Профиль успешно обновлен"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": f"Ошибка при обновлении профиля: {str(e)}"}
        )




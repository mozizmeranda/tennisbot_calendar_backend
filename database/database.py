# database.py
import aiosqlite
import os
from typing import Optional, List, Tuple, Any
import asyncio
import logging
from datetime import datetime
from functools import wraps
import traceback
from utils import notify_admin
from config.config import courts
from datetime import date as date_type
from calendar_api.grid_utils import _build_cancelled_pairs, _build_grid

logger = logging.getLogger(__name__)


def serialized_transaction(func):
    """Декоратор, который гарантирует, что методы изменения данных

    выполняются строго по очереди (100% защита от гонок данных).
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        async with self._tx_lock:
            return await func(self, *args, **kwargs)
    return wrapper


class Database:

    def __init__(self, db_name: str = "users.db"):
        self.path_to_db = os.path.join(os.path.dirname(__file__), db_name)
        self.connection: aiosqlite.Connection
        self._tx_lock = asyncio.Lock()

    async def connect(self):
        """Открывает одно глобальное соединение"""
        self.connection = await aiosqlite.connect(self.path_to_db)
        await self.connection.execute("PRAGMA foreign_keys = ON;")
        await self.connection.execute("PRAGMA busy_timeout = 5000;")
        # Безопасная миграция: добавляем поле role если его ещё нет
        try:
            await self.connection.execute(
                "ALTER TABLE calendar_members ADD COLUMN role TEXT DEFAULT 'trainer'"
            )
            await self.connection.commit()
        except Exception:
            pass  # Колонка уже существует — игнорируем

    async def close(self):
        """Закрывает соединение"""
        if self.connection:
            await self.connection.close()

    async def execute(
            self,
            sql: str,
            parameters: Optional[tuple] = None,
            fetchone: bool = False,
            fetchall: bool = False,
            commit: bool = False
    ) -> Any:
        if not parameters:
            parameters = tuple()

        if not self.connection:
            raise RuntimeError("База данных не инициализирована! Вызовите db.connect() в lifespan.")

        async with self.connection.execute(sql, parameters) as cursor:
            data = None
            if fetchone:
                data = await cursor.fetchone()
            elif fetchall:
                data = await cursor.fetchall()

            if commit:
                await self.connection.commit()

            return data

    @serialized_transaction
    async def insert_into(self, id: int, name: str, username: str, number: str, language: str):
        sql = "INSERT OR IGNORE INTO users (id, name, username, number, language, OfferOk) VALUES (?, ?, ?, ?, ?, ?)"
        params = (id, name, username, number, language, 1)
        await self.execute(sql, parameters=params, commit=True)

    async def get_user_data_by_id(self, id: int) -> Optional[Tuple[str, str]]:
        sql = "SELECT number, username FROM users WHERE id=?"
        params = (id,)
        return await self.execute(sql, parameters=params, fetchone=True)

    async def get_number_by_id(self, id: int) -> Optional[str]:
        sql = "SELECT number FROM users WHERE id=?"
        params = (id,)
        result = await self.execute(sql, parameters=params, fetchone=True)
        return result[0] if result else None

    async def get_all_users(self) -> List[Tuple[int]]:
        sql = "SELECT id FROM users"
        return await self.execute(sql, fetchall=True)

    @serialized_transaction
    async def delete_booking(self, order_id: str) -> bool:
        sql = """
        DELETE FROM bookings 
        WHERE order_id = ?
        """
        params = (order_id, )
        await self.execute(sql, parameters=params, commit=True)
        return True

    async def get_lang(self, tg_id: int) -> Optional[str]:
        sql = "SELECT language FROM users WHERE id=?"
        params = (tg_id,)
        result = await self.execute(sql, parameters=params, fetchone=True)
        return result[0] if result else None

    async def get_by_booking_id(self, booking_id: str) -> List[tuple]:
        sql = "SELECT * FROM pending_bookings WHERE booking_id=?"
        params = (booking_id,)
        return await self.execute(sql, parameters=params, fetchall=True)

    @serialized_transaction
    async def kill_from_pending_bookings(self, booking_id: str):
        sql = "DELETE FROM pending_bookings WHERE booking_id=?"
        params = (booking_id,)
        await self.execute(sql, parameters=params, commit=True)

    async def get_all_bookings(self, telegram_id: int) -> List[tuple]:
        # БЕЗОПАСНО: Исправили интерполяцию строк f"{}" на безопасные параметры ?
        sql = "SELECT * FROM bookings WHERE telegram_id=?"
        params = (telegram_id,)
        return await self.execute(sql, parameters=params, fetchall=True)

    @serialized_transaction
    async def update_user_profile(self, telegram_id: int, name: Optional[str] = None, number: Optional[str] = None):
        updates = []
        params = []
        if name is not None:
            updates.append("name=?")
            params.append(name)
        if number is not None:
            updates.append("number=?")
            params.append(number)
            
        if not updates:
            return
            
        sql = f"UPDATE users SET {', '.join(updates)} WHERE id=?"
        params.append(telegram_id)
        await self.execute(sql, parameters=tuple(params), commit=True)

    async def get_full_profile(self, telegram_id: int) -> List[tuple]:
        sql = """
           SELECT 
               u.name, 
               u.number,
               b.location, 
               b.booking_date, 
               b.time_slot, 
               b.screenshot_path
           FROM users u
           LEFT JOIN bookings b ON u.id = b.telegram_id
           WHERE u.id = ?
           """
        params = (telegram_id,)
        return await self.execute(sql, parameters=params, fetchall=True)



    async def pendings(self, location: str, day: str, time_slot: str) -> int:
        sql = "SELECT COUNT(*) FROM pending_table WHERE location=? AND booking_date=? AND time_slot=?"
        params = (location, day, time_slot)
        data = await self.execute(sql, parameters=params, fetchone=True)

        sql2 = "SELECT COUNT(*) FROM pending_bookings WHERE location=? AND booking_date=? AND time_slots=?"
        params2 = (location, day, time_slot)
        data2 = await self.execute(sql2, parameters=params2, fetchone=True)

        # Защита от None на случай пустых таблиц
        count1 = data[0] if data else 0
        count2 = data2[0] if data2 else 0
        return count1 + count2

    async def get_user_language(self, user_id: int) -> Optional[str]:
        sql = "SELECT language FROM users WHERE id = ?"
        result = await self.execute(sql, (user_id,), fetchone=True)
        return result[0] if result else None

    async def get_price(self, location: str, time_slot: str) -> Optional[int]:
        sql = "SELECT price FROM price WHERE location = ? AND time_slot = ?"
        result = await self.execute(sql, (location, time_slot), fetchone=True)
        return result[0] if result else None

    @serialized_transaction
    async def update_price(self, location: str, time_slot: str, new_price: int):
        sql = """
           UPDATE price
           SET price = ?
           WHERE location = ? AND time_slot = ?
           """
        await self.execute(sql, (new_price, location, time_slot), commit=True)

    @serialized_transaction
    async def update_user_language(self, user_id: int, new_language: str):
        sql = """
           UPDATE users
           SET language = ?
           WHERE id = ?
           """
        await self.execute(sql, (new_language, user_id), commit=True)

    @serialized_transaction
    async def delete_user_by_id(self, user_id: int) -> bool:
        sql = "DELETE FROM users WHERE id=?"
        params = (user_id,)
        await self.execute(sql, parameters=params, commit=True)
        return True

    async def get_prices_bulk(self, location: str, time_slots: list) -> list:
        if not time_slots:
            return []
        placeholders = ', '.join(['?'] * len(time_slots))
        sql = f"SELECT price FROM price WHERE location = ? AND time_slot IN ({placeholders})"
        params = (location, *time_slots)
        results = await self.execute(sql, params, fetchall=True)
        return [r[0] for r in results] if results else []

    @serialized_transaction
    async def create_pending(
        self,
        free_courts_quantity: int,
        temporary_order_id: str,
        location: str,
        booking_date: str,
        time_slot: str,
        telegram_id: int,
        expires_at: str,
    ):
        """
        Атомарно создаёт временный холд (запись в pending_table).

        Защита от race conditions:
          - asyncio.Lock (через @serialized_transaction) — только 1 запрос одновременно
          - BEGIN IMMEDIATE — write-lock на уровне SQLite

        Проверяет 3 источника занятости:
          1. pending_table    — активные холды
          2. pending_bookings — старые pending-брони
          3. single_events    — подтверждённые брони из календаря

        free_courts_quantity принимается от клиента, но ограничивается сверху
        значением из конфига (защита от подделки).

        Возвращает True если холд создан, 0 если слот занят, 0 при ошибке.
        """

        # Клиент передаёт free_courts_quantity из /free-slots.
        # Ограничиваем сверху значением из конфига: нельзя забронировать больше кортов, чем есть.
        max_courts = min(free_courts_quantity, courts.get(location, 1))
        # calendar_id по location (location и есть calendar_id, например 'A', 'B')
        calendar_id = location

        try:
            await self.connection.execute("BEGIN IMMEDIATE")

            # 1. Активные холды в pending_table
            res_table = await self.execute(
                """
                SELECT COUNT(*) FROM pending_table
                WHERE location = ? AND booking_date = ? AND time_slot = ? AND expires_at > ?
                """,
                (location, booking_date, time_slot, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                fetchone=True,
            )
            n_pending_table = res_table[0] if res_table else 0

            # 2. pending_bookings (старый механизм)
            res_bookings = await self.execute(
                "SELECT COUNT(*) FROM pending_bookings WHERE location = ? AND booking_date = ? AND time_slots = ?",
                (location, booking_date, time_slot),
                fetchone=True,
            )
            n_pending_bookings = res_bookings[0] if res_bookings else 0

            # 3. Подтверждённые брони из календаря (single_events) — источник правды
            n_single_events = 0
            if calendar_id is not None:
                # Слот формата "HH:MM-HH:MM" → парсим start/end
                parts = time_slot.split("-")
                start_str = parts[0]
                end_str = parts[1]
                start_dt = f"{booking_date} {start_str}:00"
                end_dt = (
                    f"{booking_date} {end_str}:00"
                    if end_str != "00:00"
                    else f"{booking_date[:-2]}{int(booking_date[-2:]) + 1:02d} 00:00:00"  # noqa
                )
                res_single = await self.execute(
                    """
                    SELECT COUNT(*) FROM single_events
                    WHERE calendar_id = ?
                      AND start_datetime = ?
                      AND status IN ('confirmed', 'pending_payment')
                    """,
                    (calendar_id, start_dt),
                    fetchone=True,
                )
                n_single_events = res_single[0] if res_single else 0

            total_occupied = n_pending_table + n_pending_bookings + n_single_events

            if total_occupied >= max_courts:
                await self.connection.rollback()
                return 0

            await self.connection.execute(
                """INSERT INTO pending_table
                       (temporary_order_id, location, booking_date, time_slot, telegram_id, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (temporary_order_id, location, booking_date, time_slot, telegram_id, expires_at),
            )
            await self.connection.commit()
            return True

        except aiosqlite.IntegrityError:
            await self.connection.rollback()
            return 0

        except Exception as exp:
            await self.connection.rollback()
            logger.exception(
                "Error while creating pending: telegram_id=%s, temporary_order_id=%s, exp=%s",
                telegram_id, temporary_order_id, exp,
            )
    @serialized_transaction
    async def create_pending_booking(self, booking_id: str, location: str, day: str, time_slot: str, telegram_id: int):
        sql = "INSERT INTO pending_bookings(booking_id, location, booking_date, time_slots, telegram_ID) VALUES (?, ?, ?, ?, ?)"
        params = (booking_id, location, day, time_slot, telegram_id)
        await self.execute(sql, parameters=params, commit=True)

    @serialized_transaction
    async def cancel_pending_by_order_id(self, temporary_order_id: str) -> None:
        """
        Удаляет все холды в pending_table для данного temporary_order_id.
        Используется для отката частично записанных слотов при ошибке создания брони.
        """
        await self.execute(
            "DELETE FROM pending_table WHERE temporary_order_id = ?",
            (temporary_order_id,),
            commit=True,
        )

    @serialized_transaction
    async def save_message_id(self, telegram_id: int, message_id: int, chat_id: int):
        sql = "INSERT INTO message_ids(telegram_id, message_id, chat_id) VALUES (?, ?, ?)"
        params = (telegram_id, message_id, chat_id)
        await self.execute(sql, parameters=params, commit=True)

    async def get_booked_slots(self, location: str, date_str: str) -> list:

        """
        Возвращает список занятых time_slot для данной локации и даты.
        Учитывает как single_events, так и recurring_events (с учётом отмен).
        pending_table учитывается отдельно через db.pendings().
        """

        calendar_id = location
        if not calendar_id:
            logger.warning("get_booked_slots: unknown location=%s", location)
            return []

        try:
            target_date = date_type.fromisoformat(date_str)
        except ValueError:
            logger.warning("get_booked_slots: invalid date_str=%s", date_str)
            return []

        from_str = f"{date_str} 00:00:00"
        to_str = f"{date_str} 23:59:59"

        active = await self.get_single_events_for_calendar(
            calendar_id, from_str, to_str, statuses=["confirmed", "pending_payment"]
        )
        cancelled = await self.get_single_events_for_calendar(
            calendar_id, from_str, to_str, statuses=["cancelled"]
        )
        cancelled_pairs = _build_cancelled_pairs(cancelled)
        recurring = await self.get_recurring_events_for_calendar(calendar_id)

        grid = _build_grid(active, cancelled_pairs, recurring, target_date, target_date)

        row = await self.execute("SELECT max_events_per_hour FROM calendars WHERE id=?", (calendar_id,), fetchone=True)
        max_quantity = row[0] if row else 1

        return {
            "max_quantity": max_quantity,
            "slots": [
                f"{e['start_datetime'][11:16]}-{e['end_datetime'][11:16]}"
                for e in grid
            ]
        }

    # ---------------------------------------------------------
    # Calendar DB
    # ---------------------------------------------------------

    async def check_calendar_exists(self, calendar_id: str) -> bool:
        row = await self.execute("SELECT id FROM calendars WHERE id=?", (calendar_id,), fetchone=True)
        return row is not None

    async def get_user(self, telegram_id: int) -> Optional[dict]:
        sql = "SELECT telegram_id, username, full_name, created_at FROM calendar_users WHERE telegram_id=?"
        params = (telegram_id,)
        try:
            row = await self.execute(sql, parameters=params, fetchone=True)
            if not row:
                return None
            return {
                "telegram_id": row[0],
                "username": row[1],
                "full_name": row[2],
                "created_at": row[3],
            }
        except Exception:
            logger.exception("get_user failed: telegram_id=%s", telegram_id)
            return None

    async def get_all_calendar_users(self) -> List[dict]:
        sql = "SELECT telegram_id, username, full_name, created_at FROM calendar_users"
        try:
            rows = await self.execute(sql, fetchall=True)
            if not rows:
                return []
            return [
                {
                    "telegram_id": r[0],
                    "username": r[1],
                    "full_name": r[2],
                    "created_at": r[3],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("get_all_users failed")
            return []

    @serialized_transaction
    async def create_calendar_user(
            self,
            telegram_id: int,
            username: Optional[str],
            full_name: str,
    ) -> Optional[dict]:
        sql = "INSERT OR IGNORE INTO calendar_users (telegram_id, username, full_name) VALUES (?, ?, ?)"
        params = (telegram_id, username, full_name)
        try:
            await self.execute(sql, parameters=params, commit=True)
            return await self.get_user(telegram_id)
        except Exception:
            logger.exception("create_user failed: telegram_id=%s", telegram_id)
            return None

    @serialized_transaction
    async def delete_user(self, telegram_id: int) -> bool:
        sql = "DELETE FROM calendar_users WHERE telegram_id=?"
        params = (telegram_id,)
        try:
            await self.execute(sql, parameters=params, commit=True)
            return True
        except Exception:
            logger.exception("delete_user failed: telegram_id=%s", telegram_id)
            return False

    # ──────────────────────────────────────────────────────────────────────────
    #  CALENDARS
    # ──────────────────────────────────────────────────────────────────────────

    async def get_calendar(self, calendar_id: str) -> Optional[dict]:
        sql = "SELECT id, name, max_events_per_hour, created_at FROM calendars WHERE id=?"
        params = (calendar_id,)
        try:
            row = await self.execute(sql, parameters=params, fetchone=True)
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "max_events_per_hour": row[2],
                "created_at": row[3],
            }
        except Exception:
            logger.exception("get_calendar failed: calendar_id=%s", calendar_id)
            return None

    async def get_user_calendars(self, telegram_id: int) -> List[dict]:
        sql = """
            SELECT c.id, c.name, c.max_events_per_hour, c.created_at
            FROM calendars c
            JOIN calendar_members cm ON c.id = cm.calendar_id
            WHERE cm.telegram_id=?
        """
        params = (telegram_id,)
        try:
            rows = await self.execute(sql, parameters=params, fetchall=True)
            if not rows:
                return []
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "max_events_per_hour": r[2],
                    "created_at": r[3],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("get_user_calendars failed: telegram_id=%s", telegram_id)
            return []

    @serialized_transaction
    async def create_calendar(
            self,
            id: str,
            name: str,
            max_events_per_hour: int = 1,
            owner_telegram_id: Optional[int] = None,
    ) -> Optional[dict]:
        existing = await self.get_calendar(id)
        if existing:
            return None

        try:
            await self.connection.execute(
                "INSERT INTO calendars (id, name, max_events_per_hour) VALUES (?, ?, ?)",
                (id, name, max_events_per_hour),
            )
            calendar_id = id

            if owner_telegram_id is not None:
                await self.connection.execute(
                    "INSERT OR IGNORE INTO calendar_members (calendar_id, telegram_id) VALUES (?, ?)",
                    (calendar_id, owner_telegram_id),
                )

            await self.connection.commit()
            return await self.get_calendar(calendar_id)
        except Exception:
            await self.connection.rollback()
            logger.exception("create_calendar failed: id=%s, name=%s", id, name)
            return None

    @serialized_transaction
    async def delete_calendar(self, calendar_id: str) -> bool:
        try:
            await self.connection.execute("DELETE FROM calendar_members WHERE calendar_id=?", (calendar_id,))
            await self.connection.execute("DELETE FROM single_events WHERE calendar_id=?", (calendar_id,))
            await self.connection.execute("DELETE FROM recurring_events WHERE calendar_id=?", (calendar_id,))
            await self.connection.execute("DELETE FROM calendars WHERE id=?", (calendar_id,))
            await self.connection.commit()
            return True
        except Exception:
            await self.connection.rollback()
            logger.exception("delete_calendar failed: calendar_id=%s", calendar_id)
            return False

    @serialized_transaction
    async def create_booking(
        self,
        telegram_id: int,
        location: str,
        booking_date: str,
        time_slot: str,
        screenshot_path: str = "",
        price: float = 0.0
    ):
        sql = """
        INSERT OR IGNORE INTO bookings (telegram_id, location, booking_date, time_slot, screenshot_path, price)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (telegram_id, location, booking_date, time_slot, screenshot_path, price)
        await self.execute(sql, parameters=params, commit=True)


    @serialized_transaction
    async def update_calendar_capacity(
            self, calendar_id: str, max_events_per_hour: int
    ) -> Optional[dict]:
        sql = "UPDATE calendars SET max_events_per_hour=? WHERE id=?"
        params = (max_events_per_hour, calendar_id)
        try:
            await self.execute(sql, parameters=params, commit=True)
            return await self.get_calendar(calendar_id)
        except Exception:
            logger.exception("update_calendar_capacity failed: calendar_id=%s", calendar_id)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    #  CALENDAR MEMBERS
    # ──────────────────────────────────────────────────────────────────────────

    async def check_member_access(self, calendar_id: str, telegram_id: int) -> bool:
        sql = "SELECT 1 FROM calendar_members WHERE calendar_id=? AND telegram_id=?"
        params = (calendar_id, telegram_id)
        try:
            row = await self.execute(sql, parameters=params, fetchone=True)
            return row is not None
        except Exception:
            logger.exception("check_member_access failed: calendar_id=%s, telegram_id=%s", calendar_id, telegram_id)
            return False

    async def get_calendar_members(self, calendar_id: str) -> List[dict]:
        sql = "SELECT calendar_id, telegram_id FROM calendar_members WHERE calendar_id=?"
        params = (calendar_id,)
        try:
            rows = await self.execute(sql, parameters=params, fetchall=True)
            if not rows:
                return []
            return [{"calendar_id": r[0], "telegram_id": r[1]} for r in rows]
        except Exception:
            logger.exception("get_calendar_members failed: calendar_id=%s", calendar_id)
            return []

    @serialized_transaction
    async def add_member(self, calendar_id: str, telegram_id: int, role: str = "trainer") -> Optional[dict]:
        try:
            await self.connection.execute(
                """
                INSERT INTO calendar_members (calendar_id, telegram_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(calendar_id, telegram_id) DO UPDATE SET role=excluded.role
                """,
                (calendar_id, telegram_id, role),
            )
            await self.connection.commit()
            return {"calendar_id": calendar_id, "telegram_id": telegram_id, "role": role}
        except Exception:
            logger.exception("add_member failed: calendar_id=%s, telegram_id=%s", calendar_id, telegram_id)
            return None

    async def get_member_role(self, calendar_id: str, telegram_id: int) -> Optional[str]:
        """Возвращает роль пользователя в календаре: 'admin', 'trainer' или None."""
        sql = "SELECT role FROM calendar_members WHERE calendar_id=? AND telegram_id=?"
        try:
            row = await self.execute(sql, (calendar_id, telegram_id), fetchone=True)
            return row[0] if row else None
        except Exception:
            logger.exception("get_member_role failed: calendar_id=%s, telegram_id=%s", calendar_id, telegram_id)
            return None

    async def get_monthly_stats(self, calendar_id: str, from_date: str, to_date: str) -> dict:
        """
        Возвращает статистику заработков за период из таблицы bookings.
        from_date / to_date — строки 'YYYY-MM-DD'.
        """
        try:
            rows = await self.execute(
                """
                SELECT booking_date, COUNT(*) as bookings_count, COALESCE(SUM(price), 0) as total_earned
                FROM bookings
                WHERE location = ? AND booking_date BETWEEN ? AND ?
                GROUP BY booking_date
                ORDER BY booking_date
                """,
                (calendar_id, from_date, to_date),
                fetchall=True,
            )
            daily = [
                {"date": r[0], "bookings_count": r[1], "total_earned": r[2]}
                for r in (rows or [])
            ]
            total_bookings = sum(d["bookings_count"] for d in daily)
            total_earned = sum(d["total_earned"] for d in daily)
            return {
                "from_date": from_date,
                "to_date": to_date,
                "total_bookings": total_bookings,
                "total_earned": total_earned,
                "daily": daily,
            }
        except Exception:
            logger.exception("get_monthly_stats failed: calendar_id=%s", calendar_id)
            return {"from_date": from_date, "to_date": to_date, "total_bookings": 0, "total_earned": 0, "daily": []}

    @serialized_transaction
    async def remove_member(self, calendar_id: int, telegram_id: int) -> bool:
        sql = "DELETE FROM calendar_members WHERE calendar_id=? AND telegram_id=?"
        params = (calendar_id, telegram_id)
        try:
            await self.execute(sql, parameters=params, commit=True)
            return True
        except Exception:
            logger.exception("remove_member failed: calendar_id=%s, telegram_id=%s", calendar_id, telegram_id)
            return False

    # ──────────────────────────────────────────────────────────────────────────
    #  SINGLE EVENTS
    # ──────────────────────────────────────────────────────────────────────────

    async def get_single_event(self, event_id: int) -> Optional[dict]:
        sql = """
            SELECT id, calendar_id, created_by, title,
                   start_datetime, end_datetime, status, recurring_event_id, created_at
            FROM single_events WHERE id=?
        """
        params = (event_id,)
        try:
            row = await self.execute(sql, parameters=params, fetchone=True)
            if not row:
                return None
            return {
                "id": row[0],
                "calendar_id": row[1],
                "created_by": row[2],
                "title": row[3],
                "start_datetime": row[4],
                "end_datetime": row[5],
                "status": row[6],
                "recurring_event_id": row[7],
                "created_at": row[8],
            }
        except Exception:
            logger.exception("get_single_event failed: event_id=%s", event_id)
            return None

    @serialized_transaction
    async def update_single_event(self, event_id: int, start_datetime: str, end_datetime: str, title: Optional[str] = None):
        if title:
            sql = "UPDATE single_events SET start_datetime=?, end_datetime=?, title=? WHERE id=?"
            params = (start_datetime, end_datetime, title, event_id)
        else:
            sql = "UPDATE single_events SET start_datetime=?, end_datetime=? WHERE id=?"
            params = (start_datetime, end_datetime, event_id)
            
        await self.execute(sql, parameters=params, commit=True)
        return await self.get_single_event(event_id)

    @serialized_transaction
    async def delete_single_event(self, event_id: int) -> bool:
        sql = "DELETE FROM single_events WHERE id=?"
        await self.execute(sql, parameters=(event_id,), commit=True)
        return True

    async def get_single_events_for_calendar(
            self,
            calendar_id: str,
            from_dt: str,
            to_dt: str,
            statuses: Optional[List[str]] = None,
    ) -> List[dict]:
        """
        from_dt / to_dt — строки в формате 'YYYY-MM-DD HH:MM:SS'.
        statuses — опциональный список статусов (напр. ['confirmed', 'pending_payment']).
        """
        try:
            if statuses:
                placeholders = ", ".join("?" * len(statuses))
                sql = f"""
                    SELECT id, calendar_id, created_by, title,
                           start_datetime, end_datetime, status, recurring_event_id, created_at
                    FROM single_events
                    WHERE calendar_id=? AND start_datetime>=? AND start_datetime<=?
                      AND status IN ({placeholders})
                """
                params = (calendar_id, from_dt, to_dt, *statuses)
            else:
                sql = """
                    SELECT id, calendar_id, created_by, title,
                           start_datetime, end_datetime, status, recurring_event_id, created_at
                    FROM single_events
                    WHERE calendar_id=? AND start_datetime>=? AND start_datetime<=?
                """
                params = (calendar_id, from_dt, to_dt)

            lst = []
            pending_table_sql = "SELECT * FROM pending_table WHERE booking_date BETWEEN ? AND ? AND location = ? AND expires_at > ?"
            pendinds_params = (from_dt[:10], to_dt[:10], calendar_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            pending_table = await self.execute(pending_table_sql, parameters=pendinds_params, fetchall=True)

            pending_bookings_sql = "SELECT * FROM pending_bookings WHERE booking_date BETWEEN ? AND ? AND location = ?"
            pending_bookings_params = (from_dt[:10], to_dt[:10], calendar_id)
            pending_bookings = await self.execute(pending_bookings_sql, parameters=pending_bookings_params, fetchall=True)

            if pending_table:
                for pending in pending_table:
                    lst.append(
                        {
                            "id": pending[0],
                            "calendar_id": calendar_id,
                            "created_by": 0,
                            "title": "Кто-то думает бронировать или нет....",
                            "start_datetime": f"{pending[2]} {pending[3][:5]}:00",
                            "end_datetime": f"{pending[2]} {pending[3][6:]}:00",
                            "status": "pending",
                            "recurring_event_id": 0,
                            "created_at": 0,
                        }
                    )

            if pending_bookings:
                for pending in pending_bookings:
                    lst.append(
                        {
                            "id": pending[0],
                            "calendar_id": calendar_id,
                            "created_by": 0,
                            "title": f"{pending[0]} ждет подтверждения от админа",
                            "start_datetime": f"{pending[2]} {pending[3][:5]}:00",
                            "end_datetime": f"{pending[2]} {pending[3][6:]}:00",
                            "status": "pending",
                            "recurring_event_id": 0,
                            "created_at": 0,
                        }
                    )

            rows = await self.execute(sql, parameters=params, fetchall=True)
            if not rows:
                return []
            return_rows = [
                {
                    "id": r[0],
                    "calendar_id": r[1],
                    "created_by": r[2],
                    "title": r[3],
                    "start_datetime": r[4],
                    "end_datetime": r[5],
                    "status": r[6],
                    "recurring_event_id": r[7],
                    "created_at": r[8],
                }
                for r in rows
            ]
            final = return_rows + lst
            return sorted(final, key=lambda x: x["start_datetime"])
        except Exception:
            logger.exception("get_single_events_for_calendar failed: calendar_id=%s", calendar_id)
            return []

    @serialized_transaction
    async def create_single_event(
            self,
            calendar_id: str,
            created_by: int,
            title: str,
            start_datetime: str,
            end_datetime: str,
            status: str,
            recurring_event_id: Optional[int] = None,
    ) -> Optional[dict]:
        """start_datetime / end_datetime — строки 'YYYY-MM-DD HH:MM:SS'."""
        sql = """
            INSERT INTO single_events
                (calendar_id, created_by, title, start_datetime, end_datetime, status, recurring_event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (calendar_id, created_by, title, start_datetime, end_datetime, status, recurring_event_id)
        try:
            await self.execute(sql, parameters=params, commit=True)
            row = await self.execute("SELECT last_insert_rowid()", fetchone=True)
            return await self.get_single_event(row[0])
        except Exception:
            logger.exception("create_single_event failed: calendar_id=%s", calendar_id)
            return None

    async def get_recurring_events_for_calendar(
            self,
            calendar_id: str,
            days_of_week: Optional[List[int]] = None,
    ) -> List[dict]:
        try:
            if days_of_week is not None:
                placeholders = ", ".join("?" * len(days_of_week))
                sql = f"""
                    SELECT id, calendar_id, created_by, title,
                           day_of_week, start_time, end_time, created_at
                    FROM recurring_events
                    WHERE calendar_id=? AND day_of_week IN ({placeholders})
                """
                params = (calendar_id, *days_of_week)
            else:
                sql = """
                    SELECT id, calendar_id, created_by, title,
                           day_of_week, start_time, end_time, created_at
                    FROM recurring_events WHERE calendar_id=?
                """
                params = (calendar_id,)

            rows = await self.execute(sql, parameters=params, fetchall=True)
            if not rows:
                return []
            return [
                {
                    "id": r[0],
                    "calendar_id": r[1],
                    "created_by": r[2],
                    "title": r[3],
                    "day_of_week": r[4],
                    "start_time": r[5],
                    "end_time": r[6],
                    "created_at": r[7],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("get_recurring_events_for_calendar failed: calendar_id=%s", calendar_id)
            return []

    async def get_recurring_event(self, event_id: int) -> Optional[dict]:
        sql = """
            SELECT id, calendar_id, created_by, title,
                   day_of_week, start_time, end_time, created_at
            FROM recurring_events WHERE id=?
        """
        try:
            row = await self.execute(sql, (event_id,), fetchone=True)
            if not row:
                return None
            return {
                "id": row[0],
                "calendar_id": row[1],
                "created_by": row[2],
                "title": row[3],
                "day_of_week": row[4],
                "start_time": row[5],
                "end_time": row[6],
                "created_at": row[7],
            }
        except Exception:
            logger.exception("get_recurring_event failed: event_id=%s", event_id)
            return None

    @serialized_transaction
    async def create_recurring_event(
            self,
            calendar_id: str,
            created_by: int,
            title: str,
            day_of_week: int,
            start_time: str,
            end_time: str,
    ) -> Optional[dict]:
        """start_time / end_time — строки 'HH:MM:SS'."""
        sql = """
            INSERT INTO recurring_events
                (calendar_id, created_by, title, day_of_week, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (calendar_id, created_by, title, day_of_week, start_time, end_time)
        try:
            await self.execute(sql, parameters=params, commit=True)
            row = await self.execute("SELECT last_insert_rowid()", fetchone=True)
            return await self.get_recurring_event(row[0])
        except Exception:
            logger.exception("create_recurring_event failed: calendar_id=%s", calendar_id)
            return None

    @serialized_transaction
    async def create_recurring_events_bulk(
            self,
            calendar_id: str,
            created_by: int,
            title: str,
            days_of_week: List[int],
            start_time: str,
            end_time: str,
    ) -> List[dict]:
        """Создать события для нескольких дней недели в одном коммите."""
        sql = """
            INSERT INTO recurring_events
                (calendar_id, created_by, title, day_of_week, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        try:
            ids = []
            for day in days_of_week:
                await self.connection.execute(sql, (calendar_id, created_by, title, day, start_time, end_time))
                cursor = await self.connection.execute("SELECT last_insert_rowid()")
                row = await cursor.fetchone()
                ids.append(row[0])
            await self.connection.commit()

            result = []
            for event_id in ids:
                event = await self.get_recurring_event(event_id)
                if event:
                    result.append(event)
            return result
        except Exception:
            await self.connection.rollback()
            logger.exception("create_recurring_events_bulk failed: calendar_id=%s", calendar_id)
            return []

    @serialized_transaction
    async def delete_recurring_event(self, event_id: int) -> bool:
        sql = "DELETE FROM recurring_events WHERE id=?"
        params = (event_id,)
        try:
            await self.execute(sql, parameters=params, commit=True)
            return True
        except Exception:
            logger.exception("delete_recurring_event failed: event_id=%s", event_id)
            return False

    @serialized_transaction
    async def cancel_recurring_instance(
            self,
            recurring_event_id: int,
            cancel_date: str,
            created_by: int,
    ) -> Optional[dict]:
        try:
            rec = await self.get_recurring_event(recurring_event_id)
            if not rec:
                return None

            dt = datetime.strptime(cancel_date, "%Y-%m-%d")
            if dt.weekday() != rec["day_of_week"]:
                return None

            start_dt = f"{cancel_date} {rec['start_time']}"
            end_dt = f"{cancel_date} {rec['end_time']}"

            sql = """
                INSERT INTO single_events
                    (calendar_id, created_by, title, start_datetime, end_datetime, status, recurring_event_id)
                VALUES (?, ?, ?, ?, ?, 'cancelled', ?)
            """
            params = (rec["calendar_id"], created_by, rec["title"], start_dt, end_dt, recurring_event_id)
            await self.execute(sql, parameters=params, commit=True)

            row = await self.execute("SELECT last_insert_rowid()", fetchone=True)
            return await self.get_single_event(row[0])
        except Exception:
            logger.exception("cancel_recurring_instance failed: recurring_event_id=%s", recurring_event_id)
            return None


    # ──────────────────────────────────────────────────────────────────────────
    #  STATS
    # ──────────────────────────────────────────────────────────────────────────

    async def get_calendar_stats(self, calendar_id: str) -> dict:
        """Статистика: активные, отменённые, кол-во повторяющихся серий."""
        try:
            active_row = await self.execute(
                "SELECT COUNT(*) FROM single_events WHERE calendar_id=? AND status IN ('confirmed', 'pending_payment')",
                parameters=(calendar_id,),
                fetchone=True,
            )
            cancelled_row = await self.execute(
                "SELECT COUNT(*) FROM single_events WHERE calendar_id=? AND status='cancelled'",
                parameters=(calendar_id,),
                fetchone=True,
            )
            recurring_row = await self.execute(
                "SELECT COUNT(*) FROM recurring_events WHERE calendar_id=?",
                parameters=(calendar_id,),
                fetchone=True,
            )
            return {
                "calendar_id": calendar_id,
                "active_single_events": active_row[0] if active_row else 0,
                "cancelled_events": cancelled_row[0] if cancelled_row else 0,
                "recurring_series": recurring_row[0] if recurring_row else 0,
            }
        except Exception:
            logger.exception("get_calendar_stats failed: calendar_id=%s", calendar_id)
            return {
                "calendar_id": calendar_id,
                "active_single_events": 0,
                "cancelled_events": 0,
                "recurring_series": 0,
            }

    async def get_events_on_date(self, calendar_id: str, target_date: str) -> dict:
        """
        Все активные события на конкретную дату.
        target_date — строка 'YYYY-MM-DD'.

        Возвращает: {"date": ..., "single_events": [...], "recurring_instances": [...]}
        """
        try:
            from_dt = f"{target_date} 00:00:00"
            to_dt = f"{target_date} 23:59:59"

            # Одиночные (confirmed / pending_payment)
            single_rows = await self.execute(
                """
                SELECT id, calendar_id, created_by, title,
                       start_datetime, end_datetime, status, recurring_event_id, created_at
                FROM single_events
                WHERE calendar_id=? AND start_datetime>=? AND end_datetime<=?
                  AND status IN ('confirmed', 'pending_payment')
                """,
                parameters=(calendar_id, from_dt, to_dt),
                fetchall=True,
            )

            # Отменённые экземпляры повторяющихся (чтобы исключить из виртуальных)
            cancelled_rows = await self.execute(
                """
                SELECT recurring_event_id FROM single_events
                WHERE calendar_id=? AND start_datetime>=? AND end_datetime<=?
                  AND status='cancelled' AND recurring_event_id IS NOT NULL
                """,
                parameters=(calendar_id, from_dt, to_dt),
                fetchall=True,
            )
            cancelled_ids = {r[0] for r in cancelled_rows} if cancelled_rows else set()

            # Повторяющиеся на нужный день недели (0=Пн, 6=Вс)
            weekday = datetime.strptime(target_date, "%Y-%m-%d").weekday()
            recurring_rows = await self.execute(
                """
                SELECT id, title, start_time, end_time
                FROM recurring_events
                WHERE calendar_id=? AND day_of_week=?
                """,
                parameters=(calendar_id, weekday),
                fetchall=True,
            )

            recurring_instances = [
                {
                    "recurring_event_id": r[0],
                    "title": r[1],
                    "start_datetime": f"{target_date} {r[2]}",
                    "end_datetime": f"{target_date} {r[3]}",
                    "status": "confirmed",
                    "type": "recurring_instance",
                }
                for r in (recurring_rows or [])
                if r[0] not in cancelled_ids
            ]

            return {
                "date": target_date,
                "single_events": [
                    {
                        "id": r[0],
                        "calendar_id": r[1],
                        "created_by": r[2],
                        "title": r[3],
                        "start_datetime": r[4],
                        "end_datetime": r[5],
                        "status": r[6],
                        "recurring_event_id": r[7],
                        "created_at": r[8],
                    }
                    for r in (single_rows or [])
                ],
                "recurring_instances": recurring_instances,
            }
        except Exception:
            logger.exception("get_events_on_date failed: calendar_id=%s, target_date=%s", calendar_id, target_date)
            return {"date": target_date, "single_events": [], "recurring_instances": []}


db = Database()
# asyncio.run(db.connect())
# asyncio.run(db.gg())



#!/usr/bin/env python3
"""
migrate_from_google.py
======================
Перенос событий из Google Calendar → SQLite БД.

Логика:
  1. Получает ВСЕ развёрнутые экземпляры за период (текущий + следующий месяц) с showDeleted=True.
  2. Находит ID серий, которые имеют ХОТЯ БЫ ОДИН активный (confirmed) экземпляр в периоде.
     (Это исключает старые / удалённые / завершённые серии, у которых больше нет активных событий).
  3. Для активных серий получает их шаблоны и записывает в recurring_events (для FREQ=WEEKLY).
  4. Обрабатывает развёрнутые экземпляры:
     - Неизменённые экземпляры активных серий → пропускает (покрыты recurring_events)
     - Отменённые экземпляры активных серий → single_events (status='cancelled')
     - Изменённые/перенесённые экземпляры → отмена оригинала + новый confirmed single_event
     - Одиночные / Не-weekly серии → single_events (status='confirmed')

Ограничения:
  • Часовой пояс: UTC+5 (Ташкент)
  • Максимум 1 событие в час на календарь (1 календарь = 1 корт)
  • Перед вставкой очищает старые данные для calendar_id (идемпотентно)

Использование:
  python migrate_from_google.py --dry-run   # тест без записи
  python migrate_from_google.py             # реальная миграция
"""

import asyncio
import logging
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import aiosqlite
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─── НАСТРОЙКИ ───────────────────────────────────────────────────────────────

CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"

DEFAULT_TELEGRAM_ID = 123
LOCAL_TZ = timezone(timedelta(hours=5))  # Ташкент GMT+5
DB_PATH = PROJECT_ROOT / "database" / "users.db"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# ─── ЛОГИРОВАНИЕ ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

stats = {
    "recurring": 0,
    "single": 0,
    "cancelled": 0,
    "modified": 0,
    "skipped_unmodified": 0,
    "skipped_dup": 0,
}


def reset_stats():
    for k in stats:
        stats[k] = 0


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_service():
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(f"credentials.json не найден: {CREDENTIALS_FILE}")
    creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def get_date_range() -> tuple[str, str]:
    """Сегодняшняя дата → конец следующего месяца, RFC 3339 с +05:00."""
    today = date.today()

    if today.month == 12:
        next_m = date(today.year + 1, 1, 1)
    else:
        next_m = today.replace(month=today.month + 1, day=1)

    _, last_day = monthrange(next_m.year, next_m.month)
    end = next_m.replace(day=last_day)

    return (
        f"{today.isoformat()}T00:00:00+05:00",
        f"{end.isoformat()}T23:59:59+05:00",
    )


def to_local(dt_dict: dict) -> tuple[datetime, bool]:
    """Google dateTime/date → naive datetime приведённый к UTC+5."""
    if "dateTime" in dt_dict:
        dt = datetime.fromisoformat(dt_dict["dateTime"]).astimezone(LOCAL_TZ)
        return dt.replace(tzinfo=None), False
    if "date" in dt_dict:
        return datetime.strptime(dt_dict["date"], "%Y-%m-%d"), True
    raise ValueError(f"Неизвестный формат: {dt_dict}")


def end_date_str(start_date_str: str, end_time: str) -> str:
    """
    Возвращает корректную дату для end_datetime.
    Если end_time == "00:00:00" — событие заканчивается в полночь следующего дня.
    Пример: start_date='2026-09-23', end_time='00:00:00' → '2026-09-24 00:00:00'
             start_date='2026-09-23', end_time='11:00:00' → '2026-09-23 11:00:00'
    """
    if end_time == "00:00:00":
        d = datetime.strptime(start_date_str, "%Y-%m-%d") + timedelta(days=1)
        return f"{d.strftime('%Y-%m-%d')} {end_time}"
    return f"{start_date_str} {end_time}"


def rrule_days(rrule_list: list[str], start_dt: datetime | None = None) -> list[int]:
    """
    RRULE BYDAY → список дней недели (0=Пн..6=Вс).
    Если BYDAY отсутствует — берёт день из start_dt.
    FREQ=DAILY → все 7 дней.
    """
    MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

    for rule in rrule_list:
        if "FREQ=DAILY" in rule:
            return list(range(7))

    days = []
    for rule in rrule_list:
        for part in rule.split(";"):
            if part.startswith("BYDAY="):
                for tok in part[6:].split(","):
                    key = "".join(c for c in tok if c.isalpha())
                    if key in MAP:
                        days.append(MAP[key])

    if not days and start_dt is not None:
        days = [start_dt.weekday()]

    return days


def is_simple_weekly(rrule_list: list[str]) -> bool:
    """True если RRULE — простое еженедельное (или ежедневное) повторение без INTERVAL>1."""
    for rule in rrule_list:
        if "FREQ=WEEKLY" in rule or "FREQ=DAILY" in rule:
            for part in rule.split(";"):
                if part.startswith("INTERVAL=") and part != "INTERVAL=1":
                    return False
            return True
    return False


# ─── DB HELPERS ──────────────────────────────────────────────────────────────

async def db_recurring(conn, cal_id, title, day, st, et, created_by, dry_run):
    if dry_run:
        return -1
    cur = await conn.execute(
        """INSERT INTO recurring_events
               (calendar_id, created_by, title, day_of_week, start_time, end_time)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (cal_id, created_by, title, day, st, et),
    )
    await conn.commit()
    return cur.lastrowid


async def db_single(conn, cal_id, title, s, e, status, rec_id, created_by, dry_run):
    if dry_run:
        return
    await conn.execute(
        """INSERT INTO single_events
               (calendar_id, created_by, title, start_datetime, end_datetime,
                status, recurring_event_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cal_id, created_by, title, s, e, status, rec_id),
    )
    await conn.commit()


# ─── ОСНОВНАЯ ЛОГИКА ─────────────────────────────────────────────────────────

async def migrate_calendar(service, conn, g_cal: str, db_cal: str, dry_run: bool, created_by: int = DEFAULT_TELEGRAM_ID):
    logger.info("═══ Календарь: %s → calendar_id=%s ═══", g_cal, db_cal)

    time_min, time_max = get_date_range()
    logger.info("  Период: %s — %s", time_min[:10], time_max[:10])

    today_str = date.today().isoformat() + " 00:00:00"

    # ── Очистка данных с сегодняшнего дня для идемпотентности ──
    if not dry_run:
        await conn.execute(
            "DELETE FROM single_events WHERE calendar_id=? AND start_datetime >= ?", (db_cal, today_str))
        await conn.execute(
            "DELETE FROM recurring_events WHERE calendar_id=?", (db_cal,))
        await conn.commit()
        logger.info("  Очищены данные с %s для calendar_id=%s", today_str[:10], db_cal)

    # ══════════════════════════════════════════════════════════════════════
    # ШАГ 1: Загрузка ВСЕХ экземпляров за выбранный период (с showDeleted=True)
    # ══════════════════════════════════════════════════════════════════════
    expanded_events = []
    tok = None
    while True:
        r = service.events().list(
            calendarId=g_cal,
            singleEvents=True,
            showDeleted=True,
            timeMin=time_min,
            timeMax=time_max,
            pageToken=tok,
        ).execute()
        expanded_events.extend(r.get("items", []))
        tok = r.get("nextPageToken")
        if not tok:
            break

    logger.info("  Экземпляров событий за период: %d", len(expanded_events))

    # ══════════════════════════════════════════════════════════════════════
    # ШАГ 2: Фильтрация АКТИВНЫХ серий
    # ══════════════════════════════════════════════════════════════════════
    # Ищем recurringEventId только у тех экземпляров, которые CONFIRMED в нашем периоде.
    # Если серия была полностью удалена или не имеет ни одного активного события за период,
    # она НЕ войдёт в active_parent_ids и НЕ будет создана в recurring_events!
    active_parent_ids = {
        ev["recurringEventId"]
        for ev in expanded_events
        if ev.get("recurringEventId") and ev.get("status") != "cancelled"
    }

    logger.info("  Активных серий (с подтверждёнными событиями за период): %d", len(active_parent_ids))

    # ══════════════════════════════════════════════════════════════════════
    # ШАГ 3: Получение шаблонов ТОЛЬКО для активных серий
    # ══════════════════════════════════════════════════════════════════════
    master_events = {}
    if active_parent_ids:
        tok = None
        while True:
            r = service.events().list(
                calendarId=g_cal,
                singleEvents=False,
                showDeleted=False,
                pageToken=tok,
            ).execute()
            for ev in r.get("items", []):
                g_id = ev["id"]
                if g_id in active_parent_ids and "recurrence" in ev and ev.get("status") != "cancelled":
                    master_events[g_id] = ev
            tok = r.get("nextPageToken")
            if not tok:
                break

    # series_map: google_event_id → { day_of_week → { rec_id, title, st, et } }
    series_map: dict[str, dict[int, dict]] = {}

    for g_id, ev in master_events.items():
        rrule = ev.get("recurrence", [])

        if not is_simple_weekly(rrule):
            logger.info("  [Пропуск шаблона] %s — не еженедельное правило",
                        ev.get("summary", "?"))
            continue

        title = ev.get("summary", "Без названия")
        try:
            sdt, _ = to_local(ev["start"])
            edt, _ = to_local(ev["end"])
        except Exception as e:
            logger.warning("  [Ошибка даты] %s: %s", title, e)
            continue

        days = rrule_days(rrule, start_dt=sdt)
        st = sdt.strftime("%H:%M:%S")
        et = edt.strftime("%H:%M:%S")
        series_map[g_id] = {}

        for d in days:
            rid = await db_recurring(conn, db_cal, title, d, st, et, created_by, dry_run)
            series_map[g_id][d] = {"rec_id": rid, "title": title, "st": st, "et": et}
            stats["recurring"] += 1
            logger.info("  [Серия]     %s | %s %s–%s",
                        title, DAY_NAMES[d], st[:5], et[:5])

    # ══════════════════════════════════════════════════════════════════════
    # ШАГ 4: Обработка развёрнутых экземпляров → single_events
    # ══════════════════════════════════════════════════════════════════════
    occupied: set[str] = set()

    for ev in expanded_events:
        parent_id = ev.get("recurringEventId")
        status = ev.get("status", "confirmed")
        title = ev.get("summary", "Без названия")

        # ── A: Экземпляр повторяющейся серии ──
        if parent_id:
            # 1) Отменённый экземпляр серии
            if status == "cancelled":
                orig = ev.get("originalStartTime", {})
                raw = orig.get("dateTime") or orig.get("date")
                if not raw:
                    continue
                try:
                    odt = datetime.fromisoformat(raw).astimezone(LOCAL_TZ).replace(tzinfo=None)
                except Exception:
                    continue

                day_w = odt.weekday()
                ds = odt.strftime("%Y-%m-%d")
                info = (series_map.get(parent_id) or {}).get(day_w)

                # Записываем отмену ТОЛЬКО если эта серия была добавлена в recurring_events
                if info:
                    rec_id = info["rec_id"]
                    t = info["title"]
                    s_t = info["st"]
                    e_t = info["et"]

                    await db_single(conn, db_cal, t,
                                    f"{ds} {s_t}", end_date_str(ds, e_t),
                                    "cancelled", rec_id, created_by, dry_run)
                    stats["cancelled"] += 1
                    logger.info("  [Отмена]    %s | %s %s", t, ds, s_t[:5])
                continue

            # 2) Активный (confirmed) экземпляр серии
            try:
                inst_s, allday = to_local(ev["start"])
                inst_e, _ = to_local(ev["end"])
            except Exception:
                continue
            if allday:
                continue

            orig = ev.get("originalStartTime", {})
            raw = orig.get("dateTime") or orig.get("date")
            if raw:
                try:
                    orig_dt = datetime.fromisoformat(raw).astimezone(LOCAL_TZ).replace(tzinfo=None)
                    orig_day = orig_dt.weekday()
                except Exception:
                    orig_dt = None
                    orig_day = inst_s.weekday()
            else:
                orig_dt = None
                orig_day = inst_s.weekday()

            info = (series_map.get(parent_id) or {}).get(orig_day)

            if info:
                inst_st = inst_s.strftime("%H:%M:%S")
                inst_et = inst_e.strftime("%H:%M:%S")

                is_modified = (
                    inst_st != info["st"]
                    or inst_et != info["et"]
                    or title != info["title"]
                    or inst_s.weekday() != orig_day
                )

                if not is_modified:
                    # Покрыт recurring_events
                    stats["skipped_unmodified"] += 1
                    continue

                # Изменённый экземпляр: отмена оригинала + вставка нового
                ds_orig = orig_dt.strftime("%Y-%m-%d") if orig_dt else inst_s.strftime("%Y-%m-%d")
                await db_single(conn, db_cal, info["title"],
                                f"{ds_orig} {info['st']}",
                                end_date_str(ds_orig, info['et']),
                                "cancelled", info["rec_id"], created_by, dry_run)
                stats["cancelled"] += 1

                s_str = inst_s.strftime("%Y-%m-%d %H:%M:%S")
                e_str = inst_e.strftime("%Y-%m-%d %H:%M:%S")

                if s_str not in occupied:
                    await db_single(conn, db_cal, title, s_str, e_str,
                                    "confirmed", None, created_by, dry_run)
                    occupied.add(s_str)
                    stats["modified"] += 1
                    logger.info("  [Замена]    '%s'→'%s' | %s",
                                info["title"], title, s_str[:16])
                else:
                    stats["skipped_dup"] += 1
            else:
                # Шаблон серии не создавался (не-weekly или пропущена) → переносим как одиночное
                s_str = inst_s.strftime("%Y-%m-%d %H:%M:%S")
                e_str = inst_e.strftime("%Y-%m-%d %H:%M:%S")
                if s_str not in occupied:
                    await db_single(conn, db_cal, title, s_str, e_str,
                                    "confirmed", None, created_by, dry_run)
                    occupied.add(s_str)
                    stats["single"] += 1
                    logger.info("  [Разовое*]  %s | %s", title, s_str[:16])
                else:
                    stats["skipped_dup"] += 1
            continue

        # ── B: Обычное одиночное событие ──
        if not parent_id and status != "cancelled":
            try:
                sdt, allday = to_local(ev["start"])
                edt, _ = to_local(ev["end"])
            except Exception:
                continue

            s_str = sdt.strftime(
                "%Y-%m-%d 00:00:00" if allday else "%Y-%m-%d %H:%M:%S")
            e_str = edt.strftime(
                "%Y-%m-%d 23:59:59" if allday else "%Y-%m-%d %H:%M:%S")

            if s_str not in occupied:
                await db_single(conn, db_cal, title, s_str, e_str,
                                "confirmed", None, created_by, dry_run)
                occupied.add(s_str)
                stats["single"] += 1
                logger.info("  [Разовое]   %s | %s", title, s_str[:16])
            else:
                stats["skipped_dup"] += 1
                logger.info("  [Дубль]     %s | %s — пропуск", title, s_str[:16])


async def run_google_migration(
    service,
    g_cal: str,
    db_cal: str,
    created_by: int = DEFAULT_TELEGRAM_ID,
    dry_run: bool = False,
    db_path: Path = DB_PATH,
) -> dict:
    reset_stats()
    time_min, time_max = get_date_range()

    async with aiosqlite.connect(db_path) as conn:
        await migrate_calendar(service, conn, g_cal, db_cal, dry_run, created_by=created_by)

    return {
        "status": "success",
        "calendar_id": db_cal,
        "google_calendar_id": g_cal,
        "period": {
            "from": time_min[:10],
            "to": time_max[:10],
        },
        "stats": {
            "recurring": stats["recurring"],
            "single": stats["single"],
            "cancelled": stats["cancelled"],
            "modified": stats["modified"],
            "skipped_unmodified": stats["skipped_unmodified"],
            "skipped_dup": stats["skipped_dup"],
        },
    }


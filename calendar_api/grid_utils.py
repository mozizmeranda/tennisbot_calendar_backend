# calendar_api/grid_utils.py
"""
Чистые функции для построения сетки событий.
Не импортируют database — безопасно использовать из любого модуля.
"""
from datetime import date, timedelta
from typing import List, Set, Tuple


def _build_cancelled_pairs(cancelled_events: List[dict]) -> Set[Tuple[int, str]]:
    """
    Из списка cancelled single_events строит множество (recurring_event_id, "YYYY-MM-DD"),
    чтобы отмена конкретного дня серии НЕ убивала серию на другие дни.
    """
    pairs = set()
    for e in cancelled_events:
        rec_id = e.get("recurring_event_id")
        if rec_id is None:
            continue
        start = e.get("start_datetime", "")
        date_str = start[:10] if len(start) >= 10 else ""
        if date_str:
            pairs.add((rec_id, date_str))
    return pairs


def _build_grid(
    single_rows: List[dict],
    cancelled_pairs: Set[Tuple[int, str]],
    recurring_rows: List[dict],
    from_date: date,
    to_date: date,
) -> List[dict]:
    """Собирает сетку событий из одиночных + виртуальных повторяющихся."""
    grid = []

    for e in single_rows:
        grid.append({
            "id": e["id"],
            "type": "single",
            "title": e["title"],
            "start_datetime": e["start_datetime"],
            "end_datetime": e["end_datetime"],
            "status": e["status"],
            "recurring_event_id": e["recurring_event_id"],
        })

    current = from_date
    while current <= to_date:
        weekday = current.weekday()
        date_str = current.isoformat()  # "YYYY-MM-DD"
        for re in recurring_rows:
            if re["day_of_week"] == weekday and (re["id"], date_str) not in cancelled_pairs:
                # Если событие заканчивается в полночь — end дата следующего дня
                end_date = (current + timedelta(days=1)) if re["end_time"] == "00:00:00" else current
                grid.append({
                    "id": re["id"],
                    "type": "recurring_instance",
                    "title": re["title"],
                    "start_datetime": f"{current} {re['start_time']}",
                    "end_datetime": f"{end_date} {re['end_time']}",
                    "status": "confirmed",
                    "recurring_event_id": re["id"],
                })
        current += timedelta(days=1)

    grid.sort(key=lambda e: e["start_datetime"])
    return grid

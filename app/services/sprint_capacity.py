"""Capacity-tab normalization shared with sprint planning."""
from typing import Any
from datetime import datetime, timedelta

from app.services.board_service import parse_ado_date


def normalize_capacity_members(raw_capacities: list[dict[str, Any]], start_dt: datetime | None, finish_dt: datetime | None) -> list[dict[str, Any]]:
    members = []
    for index, row in enumerate(raw_capacities):
        person = row.get("teamMember") or row.get("member") or {}
        name = str(person.get("displayName") or person.get("name") or "").strip()
        if not name:
            continue
        unique = str(person.get("uniqueName") or person.get("unique_name") or "").strip() or None
        activities = row.get("activities") or []
        names, daily = [], 0.0
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            label = str(activity.get("name") or activity.get("activity") or "").strip()
            if label:
                names.append(label)
            value = activity.get("capacityPerDay", activity.get("capacity_per_day", 0))
            daily += float(value or 0)
        # Count overlapping leave ranges once, including only sprint weekdays.
        days = set()
        for leave in row.get("daysOff") or row.get("days_off") or []:
            start, end = parse_ado_date(leave.get("start")), parse_ado_date(leave.get("end"))
            if not start or not end or not start_dt or not finish_dt:
                continue
            current, last = max(start.date(), start_dt.date()), min(end.date(), finish_dt.date())
            while current <= last:
                if current.weekday() < 5:
                    days.add(current)
                current += timedelta(days=1)
        members.append({"id": str(person.get("id") or unique or name or f"capacity-{index}"),
                        "name": name, "unique_name": unique, "activity": ", ".join(dict.fromkeys(names)) or "Development",
                        "capacity_per_day": round(daily, 2), "days_off": len(days), "source": "ado"})
    return members

# tracker.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import datetime as dt

# In-memory store (swap to Redis/DB later)
GOALS: Dict[str, "Goal"] = {}
LOGS: Dict[str, List["LogEntry"]] = {}

@dataclass
class Goal:
    user_id: str
    text: str
    pillar_key: str
    cadence: str          # "daily" | "3x/week" | "weekly"
    started: dt.date

@dataclass
class LogEntry:
    user_id: str
    date: dt.date
    note: Optional[str] = None

def set_goal(user_id: str, text: str, pillar_key: str, cadence: str, start: Optional[dt.date] = None):
    GOALS[user_id] = Goal(
        user_id=user_id,
        text=text,
        pillar_key=pillar_key,
        cadence=cadence,
        started=start or dt.date.today()
    )

def get_goal(user_id: str) -> Optional[Goal]:
    return GOALS.get(user_id)

def log_done(user_id: str, note: Optional[str] = None, date: Optional[dt.date] = None) -> LogEntry:
    entry = LogEntry(user_id=user_id, date=date or dt.date.today(), note=note)
    LOGS.setdefault(user_id, []).append(entry)
    return entry

def get_logs(user_id: str, days: int = 14) -> List[LogEntry]:
    cutoff = dt.date.today() - dt.timedelta(days=days-1)
    return [e for e in LOGS.get(user_id, []) if e.date >= cutoff]

def _expected_count(goal: Goal, days: int) -> int:
    if goal.cadence == "daily":
        return days
    if goal.cadence == "3x/week":
        # approx: 3 per 7 days
        return round(days * 3 / 7)
    if goal.cadence == "weekly":
        return max(1, round(days / 7))
    return 0

def summary(user_id: str, days: int = 14) -> str:
    g = get_goal(user_id)
    logs = get_logs(user_id, days)
    done = len(logs)
    if not g:
        return "No active goal yet. Type **baseline** to set one, or say **set goal** to define it."
    expected = _expected_count(g, days)
    adherence = 0 if expected == 0 else round(100 * done / expected)
    # streak (consecutive days with a log, counting today backwards)
    streak = 0
    day = dt.date.today()
    have = {e.date for e in LOGS.get(user_id, [])}
    while day in have:
        streak += 1
        day -= dt.timedelta(days=1)
    return (
        f"Goal: “{g.text}” (cadence: {g.cadence})\n"
        f"Last {days} days: {done}/{expected} check-ins → ~{adherence}% adherence\n"
        f"Current streak: {streak} day(s)\n"
        f"Pillar: {g.pillar_key}"
    )

def last_n_logs(user_id: str, n: int = 5) -> List[LogEntry]:
    return sorted(LOGS.get(user_id, []), key=lambda e: e.date, reverse=True)[:n]

# baseline_flow.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import datetime as dt
import re

# ---------- Domain ----------
PILLARS = [
    {"key": "environment", "label": "Environment & Structure"},
    {"key": "nutrition",   "label": "Nutrition & Gut Health"},
    {"key": "sleep",       "label": "Sleep"},
    {"key": "movement",    "label": "Exercise & Movement"},
    {"key": "stress",      "label": "Stress Management"},
    {"key": "thoughts",    "label": "Thought Patterns"},
    {"key": "emotions",    "label": "Emotional Regulation"},
    {"key": "social",      "label": "Social Connection"},
]
LABEL_BY_KEY = {p["key"]: p["label"] for p in PILLARS}
KEY_BY_LABEL = {p["label"].lower(): p["key"] for p in PILLARS}

def lowest_two(ratings: Dict[str, int]) -> List[str]:
    return [k for k,_ in sorted(ratings.items(), key=lambda kv: kv[1])[:2]]

def clamp(n: int, lo=1, hi=10) -> int:
    return max(lo, min(hi, n))

def validate_goal(text: str) -> bool:
    small = len(text.strip()) <= 180
    has_verb = bool(re.search(r"\b(I will|I'll)\b", text, re.I))
    has_when = bool(re.search(r"\b(daily|weekday|weekend|Mon|Tue|Wed|Thu|Fri|Sat|Sun|morning|evening|at \d)", text, re.I))
    return small and has_verb and has_when

# ---------- State machine ----------
INTRO, RATING, SUMMARY, PARETO, GOAL, CHECKINS, CONFIRM = range(7)

@dataclass
class Session:
    user_id: str
    phase: Optional[int] = None
    pillar_index: int = 0
    ratings: Dict[str, int] = field(default_factory=dict)
    lowest: List[str] = field(default_factory=list)
    pareto_focus: Optional[str] = None
    draft_goal: Optional[str] = None
    checkin_cadence: Optional[str] = None
    started_at: Optional[str] = None

SESSIONS: Dict[str, Session] = {}

def get_session(user_id: str) -> Session:
    if user_id not in SESSIONS:
        SESSIONS[user_id] = Session(user_id=user_id)
    return SESSIONS[user_id]

def reset_session(user_id: str):
    SESSIONS[user_id] = Session(user_id=user_id)

# ---------- Prompts ----------
def lines(*xs): return "\n".join(x for x in xs if x)

def intro_prompt():
    return lines(
        "Let’s do a quick **baseline** across the 8 pillars so I can personalise your plan.",
        "Rate each from **1–10** (1 = needs support, 10 = thriving).",
        "Type **start** when you’re ready. Type **cancel** to exit baseline."
    )

def rating_prompt(sess: Session):
    p = PILLARS[sess.pillar_index]
    return f"How would you rate **{p['label']}** right now? (1–10)"

def summary_prompt(sess: Session):
    out = ["Here’s your snapshot:"]
    for p in PILLARS:
        out.append(f"• {p['label']}: {sess.ratings.get(p['key'], '—')}")
    sess.lowest = lowest_two(sess.ratings)
    l1, l2 = sess.lowest
    out += [
        "",
        f"Your two lowest scores: **{LABEL_BY_KEY[l1]}** and **{LABEL_BY_KEY[l2]}**.",
        "Type the one to **focus** first, or type **both** to choose between them."
    ]
    return "\n".join(out)

def pareto_prompt(sess: Session):
    l1, l2 = sess.lowest
    return lines(
        "Which one would create the **biggest ripple effect** if we improved it first?",
        f"Options: **{LABEL_BY_KEY[l1]}** or **{LABEL_BY_KEY[l2]}**.",
        "Reply with the pillar name."
    )

def goal_scaffold(sess: Session):
    label = LABEL_BY_KEY[sess.pareto_focus]
    return lines(
        f"Great — we’ll start with **{label}**.",
        "Let’s set one **small, realistic, aligned** action.",
        "Use: *I will [action] on [days/time] for [duration].*",
        "Example: *I will add 1 portion of fruit at breakfast on weekdays for the next 2 weeks.*",
        "What’s your one-sentence goal?"
    )

def checkin_prompt():
    return "How often should I check in? **daily**, **3x/week**, or **weekly**."

def confirm_prompt(sess: Session):
    start = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    return lines(
        "Perfect. Here’s our plan:",
        f"• Focus pillar: **{LABEL_BY_KEY[sess.pareto_focus]}**",
        f"• Goal: “{sess.draft_goal}”",
        f"• Check-ins: **{sess.checkin_cadence}**",
        f"• Start: **{start}**",
        "",
        "Aim for **80% consistency, 20% flexibility, 100% human**.",
        "Type **baseline** anytime to run a new check-in, or **reset baseline** to start over."
    )

# ---------- Public handler ----------
def handle_baseline(user_id: str, text: str):
    """
    Returns {"reply": "..."} if the baseline flow handles this turn.
    Returns None to let the caller fall back to OpenAI coaching.
    """
    t = (text or "").strip()

    # Commands to start/reset/cancel
    if t.lower() in {"baseline", "start baseline"}:
        sess = get_session(user_id)
        sess.phase = INTRO
        sess.pillar_index = 0
        sess.ratings = {}
        sess.started_at = dt.datetime.now().isoformat()
        return {"reply": intro_prompt()}

    if t.lower() == "reset baseline":
        reset_session(user_id)
        return {"reply": "Baseline reset. Type **baseline** to start again."}

    sess = get_session(user_id)
    if sess.phase is None:
        return None

    if t.lower() in {"cancel", "exit"}:
        reset_session(user_id)
        return {"reply": "Baseline cancelled. Type **baseline** anytime to restart."}

    # Flow
    if sess.phase == INTRO:
        if t.lower() in {"start","yes","y","ok","okay","go"}:
            sess.phase = RATING
            sess.pillar_index = 0
            return {"reply": rating_prompt(sess)}
        return {"reply": intro_prompt()}

    if sess.phase == RATING:
        if t.isdigit():
            score = clamp(int(t))
            p = PILLARS[sess.pillar_index]
            sess.ratings[p["key"]] = score
            sess.pillar_index += 1
            if sess.pillar_index < len(PILLARS):
                return {"reply": rating_prompt(sess)}
            sess.phase = SUMMARY
            return {"reply": summary_prompt(sess)}
        return {"reply": "Please reply with a number from **1** to **10**."}

    if sess.phase == SUMMARY:
        tl = t.lower()
        if tl == "both":
            sess.phase = PARETO
            return {"reply": pareto_prompt(sess)}
        chosen = None
        for p in PILLARS:
            if tl == p["key"] or tl == p["label"].lower():
                chosen = p["key"]; break
        if chosen:
            sess.pareto_focus = chosen
            sess.phase = GOAL
            return {"reply": goal_scaffold(sess)}
        return {"reply": "Please type the pillar you want to **focus** on, or type **both**."}

    if sess.phase == PARETO:
        tl = t.lower()
        for k in sess.lowest:
            if tl == k or tl == LABEL_BY_KEY[k].lower():
                sess.pareto_focus = k
                sess.phase = GOAL
                return {"reply": goal_scaffold(sess)}
        return {"reply": "Please choose one of the two highlighted pillars by name."}

    if sess.phase == GOAL:
        if validate_goal(t):
            sess.draft_goal = t.strip()
            sess.phase = CHECKINS
            return {"reply": checkin_prompt()}
        return {"reply": (
            "Let’s make that smaller and time-anchored.\n"
            "Use: *I will [action] on [days/time] for [duration].*\n"
            "Example: *I will walk 10 minutes after lunch on Mon/Wed/Fri for the next 2 weeks.*"
        )}

    if sess.phase == CHECKINS:
        allowed = {"daily","3x/week","weekly","daily.","3x/week.","weekly."}
        tl = t.lower()
        if tl in allowed:
            sess.checkin_cadence = tl.rstrip(".")
            sess.phase = CONFIRM
            return {"reply": confirm_prompt(sess)}
        return {"reply": "Please choose **daily**, **3x/week**, or **weekly**."}

    if sess.phase == CONFIRM:
        if t.lower() in {"baseline","start baseline"}:
            sess.phase = INTRO
            sess.pillar_index = 0
            sess.ratings = {}
            return {"reply": intro_prompt()}
        return None

    return None

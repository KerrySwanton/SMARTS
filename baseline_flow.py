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
ALL_LABELS_LOWER = [p["label"].lower() for p in PILLARS]

# Brief descriptions shown during scoring
PILLAR_DESC: Dict[str, str] = {
    "environment": "Your routines, cues, and physical setup that make healthy choices easier.",
    "nutrition":   "Regular meals/snacks and choices that support energy, mood, and gut health.",
    "sleep":       "Quantity, quality, and regularity of your sleep and wind-down routine.",
    "movement":    "Everyday movement and/or exercise that fits your life and supports fitness.",
    "stress":      "How you recognise stress and use healthy strategies to reduce/cope.",
    "thoughts":    "Mindset and self-talk patterns that shape motivation and resilience.",
    "emotions":    "Your ability to pause, notice, and regulate emotions (including around food).",
    "social":      "Support, connection, and belonging in your relationships and community."
}

# Concrete suggestions per pillar (choose 1 to turn into a SMARTS goal)
PILLAR_SUGGESTIONS: Dict[str, List[str]] = {
    "environment": [
        "Create a 2-minute ‘start ritual’ (clear desk, fill water, set 25-min timer).",
        "Place visible cues (fruit bowl, shoes by door, vitamins on breakfast table).",
        "Night-before prep: lay out gym clothes / pack lunch / schedule tomorrow’s walk."
    ],
    "nutrition": [
        "Anchor 3 meal times (e.g., 8am, 1pm, 7pm) for the next 7 days.",
        "Add 1 portion of veg to lunch daily this week.",
        "Carry a planned snack (protein + fiber) for the afternoon dip."
    ],
    "sleep": [
        "No screens + dim lights for 30 minutes before bed.",
        "Fixed wake-time within ±30 minutes every day for 7 days.",
        "Caffeine cutoff 8 hours before bedtime."
    ],
    "movement": [
        "10-minute walk after lunch on Mon/Wed/Fri this week.",
        "1 ‘movement snack’ (stairs or 20 squats) every afternoon.",
        "Stretch 5 minutes after dinner, 4x/week."
    ],
    "stress": [
        "2-minute breathing: inhale 4, exhale 6 — once mid-day, daily.",
        "Evening brain dump: list tomorrow’s top 3 tasks before bed.",
        "Schedule a 10-minute ‘recovery block’ (walk, stretch, music) on busy days."
    ],
    "thoughts": [
        "Daily reframe: write one unhelpful thought → balanced alternative.",
        "End-of-day ‘one thing that went right’ note.",
        "Use ‘yet’ language: add ‘…yet’ to any “I can’t” thought."
    ],
    "emotions": [
        "Evening ‘pause before snacking’: water + 3 breaths + choose planned snack.",
        "Name it to tame it: label one emotion when it shows up.",
        "Identify two non-food soothers (short walk, shower, stretch) and try one nightly."
    ],
    "social": [
        "Send one short check-in message today.",
        "Book a 10-minute call/walk with someone this week.",
        "Join or re-join one group activity this month (class, club, faith/community)."
    ]
}

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
INTRO, RATING, SUMMARY, PARETO, ADVICE, GOAL, CHECKINS, CONFIRM = range(8)

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

# ---------- Helpers ----------
def lines(*xs): return "\n".join(x for x in xs if x)

def normalise_pillar_name(user_text: str) -> Optional[str]:
    """Match user text to a pillar key using label or key (case-insensitive)."""
    t = (user_text or "").strip().lower()
    if t in KEY_BY_LABEL.values() or t in [p["key"] for p in PILLARS]:
        # already a key
        for p in PILLARS:
            if t == p["key"]:
                return p["key"]
    # try label exact
    if t in KEY_BY_LABEL:
        return KEY_BY_LABEL[t]
    # try contains
    for lbl in ALL_LABELS_LOWER:
        if lbl in t:
            return KEY_BY_LABEL[lbl]
    return None

def rating_prompt(sess: Session) -> str:
    p = PILLARS[sess.pillar_index]
    desc = PILLAR_DESC[p["key"]]
    return lines(
        f"**{p['label']}** — {desc}",
        "How would you rate this right now? (1–10)"
    )

def intro_prompt() -> str:
    return lines(
        "Let’s do a quick **baseline** across the 8 pillars so I can personalise your plan.",
        "You’ll see a one-line description for each pillar. Rate 1–10 (1 = needs support, 10 = thriving).",
        "Type **start** when you’re ready. Type **cancel** to exit."
    )

def summary_prompt(sess: Session) -> str:
    out = ["Here’s your snapshot:"]
    for p in PILLARS:
        out.append(f"• {p['label']}: {sess.ratings.get(p['key'], '—')}")
    sess.lowest = lowest_two(sess.ratings)
    l1, l2 = sess.lowest
    out += [
        "",
        f"Your two lowest: **{LABEL_BY_KEY[l1]}** and **{LABEL_BY_KEY[l2]}**.",
        "Type the one to **focus** first, or type **both** to choose between them."
    ]
    return "\n".join(out)

def pareto_prompt(sess: Session) -> str:
    l1, l2 = sess.lowest
    return lines(
        "Which one would create the **biggest ripple effect** if we improved it first?",
        f"Options: **{LABEL_BY_KEY[l1]}** or **{LABEL_BY_KEY[l2]}**.",
        "Reply with the pillar name."
    )

def advice_prompt(pillar_key: str) -> str:
    label = LABEL_BY_KEY[pillar_key]
    tips = PILLAR_SUGGESTIONS[pillar_key]
    bullets = "\n".join([f"- {t}" for t in tips])
    return lines(
        f"Great — we’ll start with **{label}**.",
        "Here are a few **doable suggestions** (pick one or type your own):",
        bullets,
        "",
        "Reply with the line number (1/2/3…) or paste your own SMARTS goal."
    )

def goal_scaffold(sess: Session) -> str:
    label = LABEL_BY_KEY[sess.pareto_focus]
    return lines(
        f"Let’s shape that into a SMARTS goal for **{label}**.",
        "Use: *I will [action] on [days/time] for [duration].*",
        "Example: *I will add 1 portion of fruit at breakfast on weekdays for the next 2 weeks.*",
        "What’s your one-sentence goal?"
    )

def checkin_prompt() -> str:
    return "How often should I check in? **daily**, **3x/week**, or **weekly**."

def confirm_prompt(sess: Session) -> str:
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
        if t.lower() == "both":
            sess.phase = PARETO
            return {"reply": pareto_prompt(sess)}
        chosen = normalise_pillar_name(t)
        if chosen:
            sess.pareto_focus = chosen
            sess.phase = ADVICE
            return {"reply": advice_prompt(sess.pareto_focus)}
        return {"reply": "Please type the pillar you want to **focus** on, or type **both**."}

    if sess.phase == PARETO:
        chosen = normalise_pillar_name(t)
        if chosen and chosen in sess.lowest:
            sess.pareto_focus = chosen
            sess.phase = ADVICE
            return {"reply": advice_prompt(sess.pareto_focus)}
        return {"reply": "Please choose one of the two highlighted pillars by name."}

    if sess.phase == ADVICE:
        # Allow picking 1/2/3… or writing own goal
        if t.strip().isdigit():
            idx = int(t.strip()) - 1
            tips = PILLAR_SUGGESTIONS[sess.pareto_focus]
            if 0 <= idx < len(tips):
                # Convert suggestion into an "I will ..." scaffold if needed
                suggestion = tips[idx]
                # Nudge into SMARTS phrasing
                sess.draft_goal = f"I will {suggestion[0].lower() + suggestion[1:]} for the next 2 weeks."
                sess.phase = CHECKINS
                return {"reply": checkin_prompt()}
            else:
                return {"reply": "Pick a number from the list or type your own one-sentence goal."}
        else:
            # Treat as custom goal text; validate or move to goal scaffold
            if validate_goal(t):
                sess.draft_goal = t.strip()
                sess.phase = CHECKINS
                return {"reply": checkin_prompt()}
            else:
                sess.phase = GOAL
                return {"reply": goal_scaffold(sess)}

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

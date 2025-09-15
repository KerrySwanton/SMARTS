# smartie_playbook.py

EITY20_TAGLINE = "Aim for 80% consistency, 20% flexibility — 100% human."

# Short “voice” elements Smartie can stitch together
TONE = {
    "warm_ack": [
        "Yes - I'm here to help.",
        "You’re showing up, and that counts.",
        "Totally understandable — let’s make the next step easy.",
        "You’re not alone in this. We’ll keep it simple."
    ],
    "normalize": [
        "Progress beats perfection.",
        "Small steps, repeated, change everything.",
        "You don’t need 100% to improve meaningfully."
    ],
    "reinforce_8020": [
        EITY20_TAGLINE,
        "Consistency most of the time is what sticks.",
        "Flexible, not rigid — that’s the eity20 way."
    ],
}

# Pillar metadata + specific suggestions
PILLARS = {
    "environment": {
        "label": "Environment & Structure",
        "why": "Designing cues and routines removes friction and makes the healthy choice the easy choice.",
        "suggestions": [
            "Lay out gym clothes the night before to lower morning friction.",
            "Create a 2-minute start ritual (water, clear desk, 25-min timer).",
            "Put healthy options in sight; put tempting foods out of sight."
        ],
    },
    "nutrition": {
        "label": "Nutrition & Gut Health",
        "why": "Regular meals, plants, and fibre support energy, mood, and gut balance.",
        "suggestions": [
            "Anchor 3 meal times; add 1 veg/fruit at lunch.",
            "Carry a protein + fibre snack for the afternoon dip.",
            "Drink water with each meal; add fermented foods 3x/week."
        ],
    },
    "sleep": {
        "label": "Sleep",
        "why": "A regular wind-down and light control improve sleep quality.",
        "suggestions": [
            "Screens off and lights dim 30 minutes before bed.",
            "Keep wake time within ±30 minutes daily.",
            "Caffeine cut-off ~8 hours before bedtime."
        ],
    },
    "movement": {
        "label": "Exercise & Movement",
        "why": "Short, repeatable bouts compound and build confidence.",
        "suggestions": [
            "Walk 10 minutes after lunch on Mon/Wed/Fri.",
            "Do one ‘movement snack’ (stairs or 20 squats) each afternoon.",
            "Stretch 5 minutes after dinner, 4×/week."
        ],
    },
    "stress": {
        "label": "Stress Management",
        "why": "Brief physiological resets reduce arousal and improve decision-making.",
        "suggestions": [
            "Do 2 minutes of 4-in/6-out breathing at midday.",
            "Evening brain-dump: write tomorrow’s top 3.",
            "Schedule a 10-minute recovery block on busy days."
        ],
    },
    "thoughts": {
        "label": "Thought Patterns",
        "why": "Shifting self-talk from all-or-nothing to balanced keeps momentum.",
        "suggestions": [
            "Daily reframe one unhelpful thought → balanced alternative.",
            "Note one thing that went right today.",
            "Add “…yet” to any “I can’t” thought."
        ],
    },
    "emotions": {
        "label": "Emotional Regulation",
        "why": "Pausing before reacting widens choice and reduces autopilot.",
        "suggestions": [
            "Before stress-snacking: water + 3 breaths, then choose a planned option.",
            "Label one emotion when it shows up (“name it to tame it”).",
            "List two non-food soothers and try one tonight."
        ],
    },
    "social": {
        "label": "Social Connection",
        "why": "Brief, regular contact builds resilience and accountability.",
        "suggestions": [
            "Send one short check-in message today.",
            "Book a 10-minute walk/call this week.",
            "Join or re-join one group activity this month."
        ],
    },
}

# --- Ask-first detector -------------------------------------------------------

ADVICE_TRIGGERS = (
    "advice", "tips", "help", "ideas", "where to start",
    "what should i", "can you", "could you", "how do i",
)

def needs_clarify(user_line: str) -> bool:
    """Return True if the user asks for generic advice but gives no concrete target."""
    t = (user_line or "").lower()
    # Trigger if they ask for advice/tips/help...
    asked_for_help = any(k in t for k in ADVICE_TRIGGERS)
    # ...and there are no obvious specifics (very light heuristic)
    has_specifics = any(k in t for k in (
        # nutrition-ish
        "breakfast","lunch","dinner","snack","protein","veg","fibre","sugar",
        # sleep-ish
        "insomnia","wake","asleep","caffeine",
        # exercise-ish
        "walk","run","gym","steps","strength",
        # stress-ish
        "stress","anxious","overwhelmed","panic","breathe","relax",
        # thought/emo/social-ish
        "ruminate","worry","mindset","urge","craving","friend","lonely"
    ))
    return asked_for_help and not has_specifics

# --- Per-pillar focus options (used when asking what to cover) ----------------

FOCUS_OPTIONS = {
    "environment": ["morning start ritual", "night-before prep", "visible cues"],
    "nutrition":   ["regular meals", "protein + fibre snacks", "add 1 veg at lunch"],
    "sleep":       ["wind-down routine", "caffeine window", "consistent wake time"],
    "exercise":    ["daily walk", "2x strength weekly", "habit-stacking (after coffee)"],
    "stress":      ["2-min breath break", "worry download", "10-min walk reset"],
    "thoughts":    ["reframe self-talk", "name the thought", "tiny experiment"],
    "emotions":    ["urge-surfing", "label the feeling", "self-compassion pause"],
    "social":      ["message a friend", "ask for a small favour", "plan a 10-min chat"],
}

def compose_reply(pillar_key: str, user_line: str = "") -> str:
    """
    Advice-first reply when a user explicitly asks for help.
    If they don't ask for advice, give a short warm line + one generic tiny-step.
    """
    pk = pillar_key
    p = PILLARS.get(pk)
    if not p:
        return "Thank you for asking, what exactly would you like to know."

    text = (user_line or "").lower()

    # --- detect if user is explicitly asking for advice/help ---
    advice_markers = [
        "advice", "tip", "tips", "help", "how do i", "how to", "what should",
        "ideas", "suggest", "suggestion", "recommend", "recommendation", "plan",
        "could you", "can you", "please", "what can i do", "where to start"
    ]
    is_advice = any(m in text for m in advice_markers) or text.endswith("?")

    # --- lightweight 'specific topic' finder per pillar (skip clarify if present) ---
    focus_map = {
        "environment": ["morning routine", "evening reset", "visual cues"],
        "nutrition":   ["meal timing", "food choices", "gut balance"],
        "sleep":       ["wind-down", "night wakings", "morning light"],
        "exercise":    ["daily movement", "strength", "walks"],
        "stress":      ["breathing", "worry tools", "decompression"],
        "thoughts":    ["self-talk", "perfectionism", "reframing"],
        "emotions":    ["soothe", "urge surfing", "journalling"],
        "social":      ["ask for help", "connection", "boundaries"],
    }
    # map of quick keywords -> which suggestion index to prefer
    specific_map = {
        "nutrition": {
            "timing": 0, "breakfast": 0, "regular": 0,
            "protein": 1, "snack": 1, "veg": 1, "fruit": 1, "plants": 1,
            "gut": 2, "bloat": 2, "ibs": 2, "fibre": 2, "fiber": 2
        },
        "sleep": {
            "wind": 0, "bed": 0, "screen": 0, "caffeine": 2, "wake": 1, "waking": 1, "night": 1,
            "morning": 2, "light": 2, "sun": 2
        },
        "exercise": {"walk": 0, "steps": 0, "strength": 1, "weights": 1, "stretch": 2, "mobility": 2},
        "stress": {"breathe": 0, "breathing": 0, "worry": 1, "ruminate": 1, "rumination": 1, "pause": 2, "decompress": 2},
        "thoughts": {"self-talk": 0, "talk": 0, "kind": 0, "perfection": 1, "perfect": 1, "reframe": 2, "reframing": 2},
        "emotions": {"soothe": 0, "soothing": 0, "urge": 1, "craving": 1, "binge": 1, "comfort": 1, "journal": 2, "journalling": 2, "journaling": 2},
        "social": {"ask": 0, "help": 0, "support": 0, "friend": 1, "connect": 1, "connection": 1, "boundary": 2},
        "environment": {"morning": 0, "start": 0, "evening": 1, "reset": 1, "cue": 2, "cues": 2},
    }

    label = p["label"]
    suggestions = p["suggestions"]

    if is_advice:
        # 1) try to pick a specific suggestion based on keywords
        chosen_idx = None
        for kw, idx in specific_map.get(pk, {}).items():
            if kw in text:
                chosen_idx = idx
                break

        # 2) if not specific, ask a brief clarify question listing 3 focus options
        if chosen_idx is None and not any(k in text for k in specific_map.get(pk, {})):
            options = " / ".join(focus_map.get(pk, ["option 1", "option 2", "option 3"]))
            return (
                f"Yes — happy to help with **{label.lower()}**.\n"
                f"Which area should we focus on: {options}?\n"
                f"Tell me one and I’ll share 2–3 tiny, realistic steps."
            )

        # 3) give 2 concrete steps (rotate if needed)
if not suggestions:
    suggestions = ["Pick one 5-minute action you can repeat this week.", "Keep it realistic and time-anchored."]
s1 = suggestions[chosen_idx or 0]
s2 = suggestions[((chosen_idx or 0) + 1) % len(suggestions)]

# Offer a goal line (optional)
offer = propose_smarts_goal(pk)
goal_line = f"\n{offer['offer']}" if offer.get("offer") else ""

return "\n".join([
    "Yes — of course. Here are two tiny actions you can try:",
    f"• {s1}",
    f"• {s2}",
    EITY20_TAGLINE,
    f"(Pillar: {label})",
]) + goal_line

    # ---- default: not explicitly advice; short warm line + a generic tiny-step ----
    ack = TONE["warm_ack"][0]
    return "\n".join([
        ack,
        "Pick one tiny action you can repeat this week.",
        TONE["reinforce_8020"][0],
        f"(Pillar: {label})",
    ])

def propose_smarts_goal(pillar_key: str, idx: int = 0, duration: str = "the next 2 weeks") -> dict:
    """
    Build a SMARTS-shaped goal suggestion from the pillar library.
    Returns a dict with both the goal text and a friendly offer line.
    """
    p = PILLARS.get(pillar_key)
    if not p:
        return {"offer": None, "goal": None}

    # rotate through suggestions if idx grows
    s = p["suggestions"][idx % len(p["suggestions"])]

    goal = f"I will {s} for {duration}."
    offer = (
        "Would you like to set this as a goal?\n"
        f"• {goal}\n"
        "Reply **yes** to set it, or tell me what you’d like to change (e.g., duration, days, or wording)."
    )
    return {"offer": offer, "goal": goal}

def confirm_smarts_goal(user_text: str, default_goal: str) -> str | None:
    """
    If the user says yes/ok/sounds good, we confirm the default goal.
    If the user writes their own goal-like sentence, we accept that instead.
    Otherwise return None (no confirmation).
    """
    t = (user_text or "").strip().lower()
    if t in {"yes", "y", "ok", "okay", "sure", "sounds good", "set it", "let's do it"}:
        return default_goal

    # If user typed their own goal-ish sentence (very light heuristic)
    if any(kw in t for kw in ["i will", "my goal", "for the next", "each day", "every day", "3x/week", "twice a week"]):
        # Capitalise first letter nicely
        g = user_text.strip()
        if not g.endswith("."):
            g += "."
        return g

    return None

# smartie_playbook.py

EITY20_TAGLINE = "Aim for 80% consistency, 20% flexibility — 100% human."

# Short “voice” elements Smartie can stitch together
TONE = {
    "warm_ack": [
        "That makes sense — not every day will go perfectly.",
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

# A small template engine for consistent replies
def compose_reply(pillar_key: str, user_line: str = "") -> str:
    pk = pillar_key
    p = PILLARS.get(pk)
    if not p:
        return "\n".join([
            TONE["warm_ack"][0],
            "- Pick one tiny action you can repeat this week.",
            "- Keep it realistic and time-anchored.",
            TONE["reinforce_8020"][0],
        ])

    # pick first options (or randomize if you prefer)
    ack = TONE["warm_ack"][0]
    why = p["why"]
    s1, s2 = p["suggestions"][0], p["suggestions"][1]
    eity = TONE["reinforce_8020"][0]

    lines = [
        f"{ack} {why}",
        f"- {s1}",
        f"- {s2}",
        eity,
        f"(Pillar: {p['label']})"
    ]
    return "\n".join(lines)

# Optional: produce a SMARTS-shaped goal from a suggestion
def smarts_goal_from_suggestion(pillar_key: str, idx: int = 0, duration="the next 2 weeks"):
    p = PILLARS.get(pillar_key)
    if not p: 
        return None
    s = p["suggestions"][idx % len(p["suggestions"])]
    return f"I will {s} for {duration}."

import os
import hashlib
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# 1) Structured baseline flow (8 pillars → Pareto → SMARTS)
from baseline_flow import handle_baseline

# 2) Lightweight tracking (in-memory; see tracker.py)
from tracker import log_done, summary as tracker_summary, get_goal, last_n_logs

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --------------------------------------------------
# YOUR VOICE: small advice library + intent router
# --------------------------------------------------

PILLAR_TIPS = {
    "environment": [
        "Create a 2-minute start ritual (clear desk, fill water, set a 25-min timer).",
        "Place visible cues (fruit bowl, shoes by door, vitamins on breakfast table).",
        "Night-before prep (lay out gym clothes, pack lunch, schedule tomorrow’s walk).",
    ],
    "nutrition": [
        "Anchor 3 meal times (e.g., 8am, 1pm, 7pm) for the next 7 days.",
        "Add 1 portion of veg to lunch daily this week.",
        "Carry a planned snack (protein + fibre) for the afternoon dip.",
    ],
    "sleep": [
        "Dim lights + no screens 30 minutes before bed.",
        "Keep wake time within ±30 minutes every day for 7 days.",
        "Set a caffeine cut-off 8 hours before bedtime.",
    ],
    "movement": [
        "Walk 10 minutes after lunch on Mon/Wed/Fri this week.",
        "Do one ‘movement snack’ (stairs or 20 squats) each afternoon.",
        "Stretch 5 minutes after dinner, 4×/week.",
    ],
    "stress": [
        "Mid-day breathing: inhale 4, exhale 6 for 2 minutes.",
        "Evening brain-dump: write tomorrow’s top 3 before bed.",
        "Schedule a 10-minute recovery block (walk, stretch, music) on busy days.",
    ],
    "thoughts": [
        "Daily reframe: one unhelpful thought → a balanced alternative.",
        "End-of-day: write one thing that went right.",
        "Use ‘yet’ language: add “…yet” to any “I can’t” thought.",
    ],
    "emotions": [
        "Evening ‘pause before snacking’: water + 3 breaths + choose a planned snack.",
        "Name it to tame it: label one emotion when it shows up.",
        "List two non-food soothers (short walk, shower, stretch) and try one nightly.",
    ],
    "social": [
        "Send one short check-in message today.",
        "Book a 10-minute call/walk with someone this week.",
        "Join or re-join one group activity this month (class, club, faith/community).",
    ],
}

# Keywords → pillar
INTENT_KEYWORDS = [
    ({"stress","stressed","anxious","anxiety","tense","overwhelmed"}, "stress"),
    ({"sleep","insomnia","tired","can’t sleep","cant sleep","awake"}, "sleep"),
    ({"snack","snacking","nutrition","diet","food","eat","eating","gut"}, "nutrition"),
    ({"exercise","move","movement","workout","walk","steps"}, "movement"),
    ({"focus","clutter","organise","environment","routine","structure"}, "environment"),
    ({"negative thoughts","self talk","mindset","thoughts","motivation"}, "thoughts"),
    ({"emotions","emotional","comfort eat","urge","craving","binge"}, "emotions"),
    ({"lonely","isolated","connection","friends","social"}, "social"),
]

def map_intent_to_pillar(text: str):
    t = (text or "").lower()
    for words, pillar in INTENT_KEYWORDS:
        if any(w in t for w in words):
            return pillar
    return None

def your_voice_reply(pillar: str, user_text: str) -> str:
    """Warm, encouraging first line + 2–3 concrete steps (your voice)."""
    label = {
        "environment": "Environment & Structure",
        "nutrition": "Nutrition & Gut Health",
        "sleep": "Sleep",
        "movement": "Exercise & Movement",
        "stress": "Stress Management",
        "thoughts": "Thought Patterns",
        "emotions": "Emotional Regulation",
        "social": "Social Connection",
    }[pillar]
    tips = PILLAR_TIPS[pillar][:3]

    warm = "You’re not alone—let’s make this easier, step by step."
    if pillar in {"stress","sleep","emotions"}:
        warm = "Makes sense you’re feeling this—let’s soften it with a few doable steps."
    elif pillar in {"movement","environment"}:
        warm = "We’ll start small and make progress feel easy."

    bullets = "\n".join([f"- {t}" for t in tips])
    footer = "(Pillar: " + label + "; aim for 80% consistency, 20% flexibility, 100% human.)"
    return f"{warm}\n{bullets}\n{footer}"

# --------------------------------------------------
# Tone dial for the OpenAI fallback
# --------------------------------------------------
def style_directive(user_text: str) -> str:
    t = (user_text or "").lower()
    distress = any(w in t for w in [
        "overwhelmed","stressed","anxious","worried","exhausted","burned out",
        "failed","failing","guilty","ashamed","can't","cant","stuck","hard","struggle","struggling","depressed","low"
    ])
    celebrate = any(w in t for w in [
        "win","progress","did it","managed","proud","streak","improved","better","nailed it","success"
    ])
    if distress:
        return "STYLE=Warm, encouraging first sentence. Then 2–3 concrete, doable steps."
    if celebrate:
        return "STYLE=Enthusiastic first sentence. Then one small step-up."
    return "STYLE=Friendly, encouraging first sentence. Then 2–3 practical steps."

# --------------------------------------------------
# Smartie System Prompt for the fallback
# --------------------------------------------------
SMARTIE_SYSTEM_PROMPT = """
You are Smartie, the eity20 coach. Give short, friendly, encouraging coaching with practical next steps.

Focus areas:
• The 8 pillars: Environment & Structure, Nutrition & Gut Health, Sleep, Exercise & Movement, Stress Management, Thought Patterns, Emotional Regulation, Social Connection.
• The SMARTS framework: Sustainable, Mindful mindset, Aligned, Realistic, Train your brain, Speak up.
• The eity20 principle: 80% consistency, 20% flexibility, 100% human.
• The Pareto effect: focus on the 20% of actions that drive 80% of outcomes.

The 8 pillars of health and wellbeing:
1. Environment & Structure
2. Nutrition & Gut Health
3. Sleep
4. Exercise & Movement
5. Stress Management
6. Thought Patterns
7. Emotional Regulation
8. Social Connection

The SMARTS framework for sustainable change:
• Sustainable – choose habits you can maintain long-term (not quick fixes).
• Mindful mindset – be aware and compassionate, aim for progress not perfection.
• Aligned – set goals that reflect your values and life circumstances.
• Realistic – keep steps small and doable with current time, energy, and resources.
• Train your brain – consistency builds habits and rewires behaviour.
• Speak up – ask for support, share feelings, advocate for your needs.

Response rules:
1) Replies = 1 warm human line + 2–3 short, concrete steps.
2) Be specific and doable (time, trigger, frequency). Avoid long lectures.
3) Validate distress; celebrate wins.
4) Mention the relevant pillar or SMARTS principle once.
5) Progress over perfection (80/20). No medical diagnosis.
"""

# --------------------------------------------------
# Helper to derive a stable user_id
# --------------------------------------------------
def derive_user_id(req_json, flask_request):
    uid = (req_json or {}).get("user_id")
    if uid:
        return str(uid)
    raw = f"{flask_request.remote_addr}|{flask_request.headers.get('User-Agent','')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

# --------------------------------------------------
# Smartie Reply Endpoint
# --------------------------------------------------
@app.route("/smartie", methods=["POST"])
def smartie_reply():
    try:
        data = request.get_json() or {}
        user_input = data.get("message", "")
        user_id = derive_user_id(data, request)
        lower = (user_input or "").strip().lower()

        # 1) TRACKING (your logic) — runs before anything else
        if lower in {"done", "i did it", "check in", "check-in", "log done", "logged"}:
            _ = log_done(user_id=user_id)
            g = get_goal(user_id)
            if g:
                return jsonify({"reply": (
                    "Nice work — logged for today! ✅\n"
                    f"Goal: “{g.text}” ({g.cadence})\n"
                    "Say **progress** to see the last 14 days."
                )})
            return jsonify({"reply": "Logged! If you want this tied to a goal, run **baseline** to set one."})

        if lower in {"progress", "summary", "stats"}:
            return jsonify({"reply": tracker_summary(user_id)})

        if lower in {"history", "recent"}:
            logs = last_n_logs(user_id, 5)
            if not logs:
                return jsonify({"reply": "No check-ins yet. Say **done** whenever you complete your goal today."})
            lines = ["Recent check-ins:"] + [f"• {e.date.isoformat()}" for e in logs]
            return jsonify({"reply": "\n".join(lines)})

        if lower in {"what's my goal", "whats my goal", "goal", "show goal"}:
            g = get_goal(user_id)
            if g:
                return jsonify({"reply": f"Your goal is: “{g.text}” (cadence: {g.cadence}, pillar: {g.pillar_key})."})
            return jsonify({"reply": "You don’t have an active goal yet. Type **baseline** to set one."})

        # 2) BASELINE FLOW (your logic)
        bl = handle_baseline(user_id, user_input)
        if bl is not None:
            return jsonify(bl)

        # 3) YOUR VOICE COACHING (rule-based) — maps intent to a pillar and replies
        pillar = map_intent_to_pillar(user_input)
        if pillar:
            return jsonify({"reply": your_voice_reply(pillar, user_input)})

        # 4) AI FALLBACK (OpenAI) — only if nothing above handled it
        sd = style_directive(user_input)
        response = client.chat.completions.create(
            model="gpt-4",   # change to "gpt-3.5-turbo" if needed
            messages=[
                {"role": "system", "content": SMARTIE_SYSTEM_PROMPT},
                {"role": "user", "content": f"{sd}\n\nUser: {user_input}"}
            ],
            max_tokens=420,
            temperature=0.75,
        )
        reply = response.choices[0].message.content.strip()
        return jsonify({"reply": reply})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"reply": "Oops—something went wrong. Try again in a moment."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

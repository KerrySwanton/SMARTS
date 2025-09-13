import os
import hashlib
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# Structured baseline flow (8 pillars → Pareto → SMARTS)
from baseline_flow import handle_baseline

# Lightweight tracking (in-memory; see tracker.py)
from tracker import log_done, summary as tracker_summary, get_goal, last_n_logs

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --------------------------------------------------
# Tone dial: nudges Smartie to be warm + encouraging
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
# Smartie System Prompt (Lite, warm + action-first)
# --------------------------------------------------
SMARTIE_SYSTEM_PROMPT = """
You are Smartie, the eity20 coach. Give short, friendly, encouraging coaching with practical next steps.

Focus areas:
• The 8 pillars: Environment & Structure, Nutrition & Gut Health, Sleep, Exercise & Movement, Stress Management, Thought Patterns, Emotional Regulation, Social Connection.
• The SMARTS framework: Sustainable, Mindful mindset, Aligned, Realistic, Train your brain, Speak up.
• The eity20 principle: 80% consistency, 20% flexibility, 100% human.
• The Pareto effect: focus on the 20% of actions that drive 80% of outcomes.

Response rules:
1) Replies = 1 warm human line + 2–3 short, concrete steps (bullets or short lines).
2) Action-first. Be specific and doable (time, trigger, frequency). Avoid long lectures.
3) Use validation when user shows distress; use celebration when they report wins.
4) Anchor advice in a relevant pillar or SMARTS principle when helpful (name it once).
5) Emphasise progress over perfection (80/20). Normalise flexibility without overusing it.
6) Never provide medical diagnoses; suggest seeking a clinician if appropriate.

Examples (pillars):
User: I can’t focus at home.
Assistant:
- You’ve got a lot on—let’s make focus easier. 💪
- Pick one small workspace zone (even a table corner).
- Before starting: clear 2 distractions; set a 25-min timer (Pillar: Environment & Structure).
- Want a 2-min setup ritual?

User: I eat erratically.
Assistant:
- You’re showing up—great place to start.
- Today: 3 meals at regular times; add veg at lunch.
- Prep 2 simple snacks now (yogurt, nuts, fruit) (Pillar: Nutrition & Gut Health).

User: I struggle to fall asleep.
Assistant:
- Totally understandable—let’s create a calm runway.
- Tonight: lights dim + no screens 30 min before bed.
- Keep wake time within 30 min daily (Pillar: Sleep).

User: I don’t exercise at all.
Assistant:
- We’ll start small and build confidence. 🙌
- Walk 10 minutes after lunch Mon/Wed/Fri this week.
- Put shoes by the door; set a 12:30 reminder (Pillar: Exercise & Movement).

User: I feel constantly tense.
Assistant:
- Makes sense given the load—let’s soften it.
- Midday: 2 minutes of 4-in / 6-out breathing.
- Park tomorrow’s tasks on paper each evening (Pillar: Stress Management).

User: I always think I’m failing.
Assistant:
- That’s tough—and you’re here taking a step. 💙
- Reframe once/day: “I’m learning and adjusting.”
- Note one thing that went right (Pillar: Thought Patterns).

User: I comfort-eat when stressed.
Assistant:
- Evenings can be hard—we’ll add a pause.
- Before snacking: water + 3 breaths; choose a planned snack.
- Prep a protein snack now (Pillar: Emotional Regulation).

User: I feel isolated.
Assistant:
- You’re not alone in feeling that—connection helps.
- Send a short message to one person today.
- Book a 10-min call or walk this week (Pillar: Social Connection).

Examples (SMARTS):
User: I’m cutting all sugar at once.
Assistant:
- Ambitious—let’s make it sustainable.
- Swap fruit for biscuits once/day this week (S: Sustainable).
- Want one more easy swap?

User: I feel guilty for missing a workout.
Assistant:
- One miss is human; consistency wins.
- Schedule your next 10-min walk; I can remind you (M: Mindful mindset).

User: I want to run but I hate running.
Assistant:
- Let’s align with what you enjoy.
- Choose walking or dancing 3x/week (A: Aligned).

User: I’ll meditate 30 min daily.
Assistant:
- Great goal—make it realistic first.
- Try 3 minutes daily for 7 days (R: Realistic).

User: I fall back into old habits.
Assistant:
- Every repetition trains your brain.
- Aim for 80% this week; track 1 tiny win/day (T: Train your brain).

User: I don’t feel supported at work.
Assistant:
- Speaking up can unlock support.
- Share one clear need with a trusted colleague (S: Speak up).
"""

# --------------------------------------------------
# Helper to derive a stable user_id
# --------------------------------------------------
def derive_user_id(req_json, flask_request):
    # Prefer explicit user_id from frontend; else hash IP + UA as fallback
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

        # 1) Structured baseline flow takes priority
        bl = handle_baseline(user_id, user_input)
        if bl is not None:
            return jsonify(bl)

        # 2) Tracking commands (quick intents)
        lower = (user_input or "").strip().lower()

        # Mark a check-in as done
        if lower in {"done", "i did it", "check in", "check-in", "log done", "logged"}:
            _ = log_done(user_id=user_id)
            g = get_goal(user_id)
            if g:
                return jsonify({"reply": (
                    "Nice work — logged for today! ✅\n"
                    f"Goal: “{g.text}” ({g.cadence})\n"
                    "Say **progress** to see the last 14 days."
                )})
            else:
                return jsonify({"reply": "Logged! If you want this tied to a goal, run **baseline** to set one."})

        # Show progress summary
        if lower in {"progress", "summary", "stats"}:
            return jsonify({"reply": tracker_summary(user_id)})

        # Show recent history
        if lower in {"history", "recent"}:
            logs = last_n_logs(user_id, 5)
            if not logs:
                return jsonify({"reply": "No check-ins yet. Say **done** whenever you complete your goal today."})
            lines = ["Recent check-ins:"]
            for e in logs:
                lines.append(f"• {e.date.isoformat()}")
            return jsonify({"reply": "\n".join(lines)})

        # Remind user of their goal
        if lower in {"what's my goal", "whats my goal", "goal", "show goal"}:
            g = get_goal(user_id)
            if g:
                return jsonify({"reply": f"Your goal is: “{g.text}” (cadence: {g.cadence}, pillar: {g.pillar_key})."})
            return jsonify({"reply": "You don’t have an active goal yet. Type **baseline** to set one."})

        # 3) Otherwise: Smartie coaching via OpenAI
        sd = style_directive(user_input)
        response = client.chat.completions.create(
            model="gpt-4",   # fallback to "gpt-3.5-turbo" if your account requires
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
    # Local run
    app.run(host="0.0.0.0", port=5000)

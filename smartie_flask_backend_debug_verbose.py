# smartie_flask_backend_debug_verbose.py

import os
import hashlib
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from twilio.rest import Client

# Playbook (single source of truth for tone + advice)
from smartie_playbook import (
    compose_reply, PILLARS, EITY20_TAGLINE,
    nutrition_rules_answer, NUTRITION_RULES_TRIGGERS,
    nutrition_foods_answer, FOODS_TRIGGERS
)

# Baseline + tracking
from baseline_flow import handle_baseline
from tracker import log_done, summary as tracker_summary, get_goal, last_n_logs

PENDING_GOALS: dict[str, dict] = {}
CONCERN_CHOICES: dict[str, dict] = {}

# ==================================================
# Safety-first + concern mapping + intent helpers
# ==================================================

# 1) Red-flag terms → safety script
SAFETY_TERMS = {
    # mental health crisis
    "suicide", "suicidal", "self harm", "self-harm", "kill myself", "end it", "i want to die",
    # acute physical
    "chest pain", "severe chest pain", "struggling to breathe", "can’t breathe", "cant breathe",
    "fainted", "passing out", "severe bleeding", "stroke", "numb face", "numb arm",
}

def safety_check_and_reply(text: str) -> str | None:
    t = (text or "").lower()
    if any(term in t for term in SAFETY_TERMS):
        return (
            "I’m concerned about your safety. If you’re in immediate danger, call emergency services now "
            "(999 UK / 112 EU / 911 US).\n\n"
            "• Mental health crisis (UK): Samaritans 116 123 or text SHOUT to 85258.\n"
            "• Severe physical symptoms: please seek urgent medical care.\n\n"
            "Smartie supports lifestyle change, but crises need urgent human help."
        )
    return None

    return None

# --- Priority concerns (curated pillar stacks, skip/short-circuit baseline) ---
PRIORITY_CONCERNS: dict[str, list[str]] = {
    "binge-eating": ["nutrition", "environment", "emotions", "thoughts"],
    "emotional eating": ["nutrition", "environment", "emotions", "thoughts"],
    "comfort eating": ["nutrition", "environment", "emotions", "thoughts"],
    "bulimia": ["nutrition", "environment", "emotions", "thoughts"],
    "ibs": ["nutrition", "stress", "sleep", "emotions"],
    "hypertension": ["nutrition", "movement", "stress", "sleep"],
    "high blood pressure": ["nutrition", "movement", "stress", "sleep"],
    "anxiety": ["stress", "thoughts", "sleep", "emotions"],
    "panic": ["stress", "thoughts", "sleep", "emotions"],
    "low mood": ["sleep", "movement", "thoughts", "social"],
    "depression": ["sleep", "movement", "thoughts", "social"],
}

# --- Priority concern detector ---
def detect_priority_stack(text: str) -> list[str]:
    """
    Check if the user mentioned a priority concern that maps to a curated pillar stack.
    Returns a list of pillar keys in priority order.
    """
    t = (text or "").lower()

    PRIORITY_CONCERNS = {
        "binge-eating": ["nutrition", "environment", "emotions", "thoughts"],
        "eating disorder": ["nutrition", "emotions", "thoughts", "social"],
        "adhd": ["environment", "nutrition", "sleep", "thoughts"],
        # add more special cases here...
    }

    for k, stack in PRIORITY_CONCERNS.items():
        if k in t:
            return stack

    return []

# 2) Concern → suggested pillars (extended matrix)
CONCERN_TO_PILLARS = {
    # --- Physical Health ---
    "cholesterol": ["nutrition","movement","environment"],
    "overweight": ["nutrition","movement","thoughts","stress"],
    "obese": ["nutrition","movement","thoughts","stress"],
    "glp-1": ["nutrition","movement","thoughts"],
    "blood sugar": ["nutrition","movement","sleep","stress"],
    "type 2 diabetes": ["nutrition","movement","sleep","stress"],
    "pre-diabetes": ["nutrition","movement","sleep","stress"],
    "menopause": ["sleep","stress","emotions","social"],
    "hypertension": ["nutrition","movement","stress","sleep"],
    "blood pressure": ["nutrition","movement","stress","sleep"],
    "osteoarthritis": ["movement","stress","environment"],
    "joint pain": ["movement","stress","environment"],
    "coronary heart disease": ["movement","nutrition","stress"],
    "atrial fibrillation": ["stress","sleep","nutrition"],
    "copd": ["breathing","movement","stress","sleep"],
    "asthma": ["breathing","stress","environment"],
    "sleep apnoea": ["sleep","weight","stress"],
    "liver disease": ["nutrition","environment","stress"],
    "fatty liver": ["nutrition","movement","environment"],
    "kidney disease": ["nutrition","stress","movement"],
    "bone health": ["movement","nutrition","environment"],
    "osteoporosis": ["movement","nutrition","environment"],
    "osteopenia": ["movement","nutrition","environment"],
    "metabolic syndrome": ["nutrition","movement","stress","sleep"],
    "autoimmune disorder": ["stress","emotions","nutrition","sleep"],
    "rheumatoid arthritis": ["movement","stress","emotions"],
    "psoriasis": ["stress","emotions","social"],
    "multiple sclerosis": ["movement","emotions","social"],

    # --- Mental Health (ICD-11 categories) ---
    "low mood": ["sleep","movement","thoughts","social"],
    "depression": ["sleep","movement","thoughts","social"],
    "bipolar": ["sleep","stress","emotions","social"],
    "sad": ["sleep","thoughts","movement","social"],   # Seasonal Affective Disorder
    "anxiety": ["stress","thoughts","sleep","emotions"],
    "gad": ["stress","thoughts","sleep","emotions"],   # Generalised Anxiety Disorder
    "ptsd": ["stress","emotions","social"],
    "stress": ["stress","thoughts","emotions"],
    "emotional dysregulation": ["emotions","thoughts","social"],
    "binge eating": ["nutrition","emotions","thoughts"],
    "adhd": ["environment","structure","movement","thoughts"],
    "asd": ["social","environment","thoughts"],
    "gaming": ["environment","thoughts","movement"],
    "addiction": ["emotions","thoughts","social"],
    "insomnia": ["sleep","stress","environment"],
    "sleep disorder": ["sleep","stress","environment"],
    "cognitive decline": ["thoughts","social","movement"],
    "mild neurocognitive disorder": ["thoughts","movement","social"],
    "dementia": ["thoughts","social","environment"],
    "alzheimer": ["thoughts","social","movement"],

    # --- Gut Health ---
    "bloating": ["nutrition","gut","stress"],
    "constipation": ["nutrition","gut","movement"],
    "diarrhoea": ["nutrition","gut","stress"],
    "functional gi": ["nutrition","gut","stress","emotions"],
    "ibs": ["nutrition","stress","sleep","emotions"],
    "leaky gut": ["nutrition","gut","emotions"],
    "food allergy": ["nutrition","environment"],
    "food intolerance": ["nutrition","environment"],
    "gluten": ["nutrition","gut"],
    "dairy": ["nutrition","gut"],
    "wheat": ["nutrition","gut"],
    "histamine": ["nutrition","gut"],
    "gerd": ["nutrition","sleep","environment"],
    "acid reflux": ["nutrition","sleep","environment"],
    "crohn": ["nutrition","stress","emotions"],
    "ulcerative colitis": ["nutrition","stress","emotions"],
    "coeliac": ["nutrition","gut","emotions"],
    "autoimmune gastritis": ["nutrition","stress","gut"],
}

def suggest_pillars_for_concern(text: str) -> list[str]:
    t = (text or "").lower()
    hits: list[str] = []
    for k, pillars in CONCERN_TO_PILLARS.items():
        if k in t:
            for p in pillars:
                if p not in hits:
                    hits.append(p)
    return hits

# 3) Intent keywords → pillar (fast routing to your playbook)
INTENT_KEYWORDS = [
    ({"stress", "stressed", "anxious", "anxiety", "tense", "overwhelmed"}, "stress"),
    ({"sleep", "insomnia", "tired", "can't sleep", "cant sleep", "awake"}, "sleep"),
    ({"snack", "snacking", "nutrition", "diet", "food", "eat", "eating", "gut", "ibs"}, "nutrition"),
    ({"exercise", "move", "movement", "workout", "walk", "steps"}, "movement"),
    ({"focus", "clutter", "organise", "organize", "routine", "structure", "environment"}, "environment"),
    ({"negative thoughts", "self talk", "self-talk", "mindset", "thoughts", "motivation"}, "thoughts"),
    ({"emotions", "emotional", "urge", "craving", "binge", "comfort eat", "comfort-eat"}, "emotions"),
    ({"lonely", "isolated", "connection", "friends", "social"}, "social"),
]

def map_intent_to_pillar(text: str) -> str | None:
    t = (text or "").lower()
    for words, pillar in INTENT_KEYWORDS:
        if any(w in t for w in words):
            return pillar
    # fallback to concern mapping
    sp = suggest_pillars_for_concern(t)
    return sp[0] if sp else None

# 4) Tone nudger for the OpenAI fallback
def style_directive(user_text: str) -> str:
    t = (user_text or "").lower()
    distress = any(w in t for w in [
        "overwhelmed", "stressed", "anxious", "worried", "exhausted",
        "burned out", "failed", "guilty", "ashamed", "stuck", "struggle"
    ])
    celebrate = any(w in t for w in [
        "win", "progress", "did it", "managed", "proud", "streak", "improved", "better", "nailed it", "success"
    ])
    if distress:
        return "STYLE=Warm, encouraging first line. Then 2–3 concrete, doable steps."
    if celebrate:
        return "STYLE=Enthusiastic first line. Then one small step-up."
    return "STYLE=Friendly first line. Then 2–3 practical steps."

# 5) System prompt for the fallback
SMARTIE_SYSTEM_PROMPT = """
You are Smartie, the eity20 coach. Give short, friendly, encouraging coaching with practical next steps.

Focus areas:
• The 8 pillars: Environment & Structure, Nutrition & Gut Health, Sleep, Exercise & Movement, Stress Management, Thought Patterns, Emotional Regulation, Social Connection.
• The SMARTS framework: Sustainable, Mindful mindset, Aligned, Realistic, Train your brain, Speak up.
• The eity20 principle: 80% consistency, 20% flexibility, 100% human.
• The Pareto effect: focus on the 20% of actions that drive 80% of outcomes.

Response rules:
1) Replies = 1 warm human line + 2–3 short, concrete steps.
2) Be specific and doable (time, trigger, frequency). Avoid long lectures.
3) Validate distress; celebrate wins.
4) Mention the relevant pillar or SMARTS principle once.
5) Progress over perfection (80/20). No medical diagnosis.
"""

# --- Priority concern detector (skip/short-circuit baseline when matched) ---
def detect_priority_stack(text: str) -> list[str]:
    """
    Return a curated, ordered list of pillar keys for priority concerns.
    If nothing matches, return [] and the normal flow continues.
    Pillar keys: "environment","nutrition","sleep","movement",
                 "stress","thoughts","emotions","social"
    """
    t = (text or "").lower()

    PRIORITY_MAP: list[tuple[tuple[str, ...], list[str]]] = [
        # ------------------ Physical health ------------------
        (("cholesterol","hyperlipid","dyslipid"),                     ["nutrition","movement","environment"]),
        (("overweight","obese","weight","weight loss","weight-loss",
          "glp-1","ozempic","wegovy","mounjaro","tirzepatide","semaglutide"),
                                                                     ["nutrition","movement","thoughts","environment"]),
        (("blood sugar","insulin resistance","type 2 diabetes","t2d",
          "pre-diabetes","prediabetes"),                             ["nutrition","movement","sleep","stress"]),
        (("menopause","perimenopause","peri-menopause"),             ["sleep","stress","emotions","social"]),
        (("hypertension","high blood pressure","blood pressure"),    ["nutrition","movement","stress","sleep"]),
        (("osteoarthritis","arthritis","joint pain"),                ["movement","stress","environment","sleep"]),
        (("coronary heart disease","chd","atrial fibrillation","afib","a-fib"),
                                                                     ["nutrition","movement","stress","sleep"]),
        (("copd","asthma","breathing difficulties","sleep apnoea","sleep apnea"),
                                                                     ["movement","sleep","stress","environment"]),
        (("liver disease","alcohol-related liver disease","arld",
          "non-alcoholic fatty liver disease","nafld","fatty liver"),
                                                                     ["nutrition","movement","stress","sleep"]),
        (("kidney disease","ckd","chronic kidney"),                  ["nutrition","sleep","stress","movement"]),
        (("osteopenia","osteoporosis","bone health"),                ["movement","nutrition","environment","sleep"]),
        (("metabolic syndrome","high triglycerides","low hdl","large waist","waist circumference"),
                                                                     ["nutrition","movement","sleep","stress"]),
        (("autoimmune","multiple sclerosis","ms","graves","type 1 diabetes",
          "rheumatoid arthritis","psoriasis","vasculitis"),          ["stress","nutrition","movement","sleep"]),

        # ------------------ Mental health (ICD-11-ish) ------------------
        (("low mood","depression","bipolar","seasonal affective","sad"),
                                                                     ["sleep","movement","thoughts","social"]),
        (("anxiety","gad","generalised anxiety","generalized anxiety"),
                                                                     ["stress","thoughts","sleep","emotions"]),
        (("ptsd","post-traumatic stress","stress disorder","trauma"),["stress","emotions","social","sleep"]),
        (("emotional dysregulation","emotional disorder","binge eating","binge-eating",
          "emotional eating","comfort eating","eating disorder","bed"),
                                                                     ["nutrition","environment","emotions","thoughts"]),
        (("adhd","attention deficit","asd","autism","neurodevelopmental"),
                                                                     ["environment","nutrition","sleep","thoughts"]),
        (("addiction","addictive behaviour","gaming","screen time","television","tv"),
                                                                     ["environment","thoughts","social","sleep"]),
        (("sleep-wake","circadian","insomnia","sleep disorder"),     ["sleep","environment","stress","thoughts"]),
        (("mci","cognitive decline","neurocognitive","dementia","alzheimer"),
                                                                     ["sleep","nutrition","movement","social"]),

        # ------------------ Gut health ------------------
        (("ibs","irritable bowel","bloating","constipation","diarrhoea","diarrhea"),
                                                                     ["nutrition","stress","sleep","emotions"]),
        (("leaky gut","intestinal permeability","crohn","ulcerative colitis","ibd",
          "coeliac","celiac","autoimmune gastritis"),
                                                                     ["nutrition","stress","sleep","emotions"]),
        (("food allergy","food intolerance","gluten","dairy","wheat","histamine","mold","mould",
          "reflux","gerd","acid reflux"),
                                                                     ["nutrition","emotions","stress","sleep"]),
    ]

    for aliases, stack in PRIORITY_MAP:
        if any(k in t for k in aliases):
            return stack

    return []

# ==================================================
# Unified router
# ==================================================
def route_message(user_id: str, text: str) -> dict:
    lower = (text or "").strip().lower()
    tag = f"\n{EITY20_TAGLINE}" if 'EITY20_TAGLINE' in globals() else ""

    # --- 1) Safety first ---
    s = safety_check_and_reply(text)
    if s:
        return {"reply": s}

    # --- 2) Quick commands: tracking ---
    if lower in {"done", "i did it", "check in", "check-in", "log done", "logged"}:
        _ = log_done(user_id=user_id)
        g = get_goal(user_id)
        if g:
            return {"reply": (
                "Nice work — logged for today! ✅\n"
                f"Goal: “{g.text}” ({g.cadence})\n"
                "Say **progress** to see the last 14 days."
            ) + tag}
        return {"reply": "Logged! If you want this tied to a goal, run **baseline** to set one." + tag}

    if lower in {"progress", "summary", "stats"}:
        return {"reply": tracker_summary(user_id) + tag}

    if lower in {"history", "recent"}:
        logs = last_n_logs(user_id, 5)
        if not logs:
            return {"reply": "No check-ins yet. Say **done** whenever you complete your goal today." + tag}
        lines = ["Recent check-ins:"] + [f"• {e.date.isoformat()}" for e in logs]
        return {"reply": "\n".join(lines) + tag}

    if lower in {"what's my goal", "whats my goal", "goal", "show goal"}:
        g = get_goal(user_id)
        if g:
            return {"reply": f"Your goal is: “{g.text}” (cadence: {g.cadence}, pillar: {g.pillar_key})." + tag}
        return {"reply": "You don’t have an active goal yet. Type **baseline** to set one." + tag}

    # --- 3) Concern-first: skip/short-circuit baseline when a priority concern is mentioned ---
    stack = detect_priority_stack(text)  # make sure this helper is defined/imported
    if stack:
        first = stack[0]
        reply = compose_reply(first, text)  # give immediate, pillar-specific advice
        if len(stack) > 1:
            rest_labels = [PILLARS[p]["label"] for p in stack[1:] if p in PILLARS]
            if rest_labels:
                reply += "\n\nNext we can explore: " + ", ".join(rest_labels) + "."
        return {"reply": reply + tag}

    # --- 4) Onboarding / Baseline / Set a SMARTS goal ---
    if lower in {"start", "get started", "baseline", "onboard", "begin"}:
        bl = handle_baseline(user_id, text)   # asks concern → 8 ratings → suggest pillar → set goal
        if bl is not None:
            return bl

    # Continue baseline if mid-session
    bl = handle_baseline(user_id, text)
    if bl is not None:
        return bl

    # --- 5) Pillar advice (direct keywords → playbook) ---

    # Environment & Structure
    if any(k in lower for k in ["environment", "structure", "routine", "organise", "organize"]):
        return {"reply": compose_reply("environment", text)}

    # Nutrition & Gut Health  (with special nutrition sub-branches)
    if any(k in lower for k in ["nutrition", "gut", "food", "diet", "ibs", "bloating"]):
        # 5a) Nutrition rules (SMARTS / eity20 guidance)
        if any(k in lower for k in NUTRITION_RULES_TRIGGERS):
            return {"reply": nutrition_rules_answer()}
        # 5b) Food lists / 80–20 foods
        if any(k in lower for k in FOODS_TRIGGERS):
            return {"reply": nutrition_foods_answer()}
        # 5c) General nutrition coaching (playbook)  ← fixed indent (sibling of 5a/5b)
        return {"reply": compose_reply("nutrition", text)}

    # Sleep
    if any(k in lower for k in ["sleep", "insomnia", "tired", "can't sleep", "cant sleep"]):
        return {"reply": compose_reply("sleep", text)}

    # Exercise & Movement
    if any(k in lower for k in ["exercise", "movement", "workout", "walk", "steps"]):
        return {"reply": compose_reply("exercise", text)}

    # Stress Management
    if any(k in lower for k in ["stress", "stressed", "anxiety", "anxious", "overwhelmed"]):
        return {"reply": compose_reply("stress", text)}

    # Thought Patterns
    if any(k in lower for k in ["thought", "mindset", "self-talk", "self talk", "motivation"]):
        return {"reply": compose_reply("thoughts", text)}

    # Emotional Regulation
    if any(k in lower for k in ["emotion", "feelings", "craving", "urge", "binge", "comfort eat", "comfort-eat"]):
        return {"reply": compose_reply("emotions", text)}

    # Social Connection
    if any(k in lower for k in ["social", "connection", "friends", "lonely", "isolation", "isolated"]):
        return {"reply": compose_reply("social", text)}

    # --- 6) Intent/concern mapper → pillar → playbook (support mode) ---
    pillar = map_intent_to_pillar(text)
    if pillar:
        return {"reply": compose_reply(pillar, text)}

    # If user stated a clear concern, suggest pillars explicitly
    pillars = suggest_pillars_for_concern(text)
    if pillars:
        labels = [PILLARS[p]["label"] for p in pillars if p in PILLARS]
        suggestion = ", ".join(labels[:3]) or ", ".join(pillars[:3])
        return {"reply": (
            f"Thanks — that helps focus the right areas. These pillars usually help most: {suggestion}.\n"
            f"Want to do a 1-minute baseline and pick one to start?\n{EITY20_TAGLINE}"
        )}

    # --- 7) OpenAI fallback (short, warm, actionable, 80/20 tone) ---
    sd = style_directive(text)
    response = client.chat.completions.create( 
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SMARTIE_SYSTEM_PROMPT},
            {"role": "user", "content": f"{sd}\n\nUser: {text}"},
        ],
        max_tokens=420,
        temperature=0.75,
    )
    return {"reply": response.choices[0].message.content.strip() + tag}

# ==================================================
# Flask app + OpenAI client
# ==================================================
app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# ==================================================
# Twilio WhatsApp setup
# ==================================================
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
WA_NUMBER   = os.getenv("TWILIO_WHATSAPP_NUMBER")   # e.g. "whatsapp:+14155238886"

twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)

def send_wa(to_e164: str, body: str):
    """
    Send a WhatsApp message via Twilio.
    to_e164: recipient in E.164 without the 'whatsapp:' prefix (e.g., '+447700900123')
    """
    return twilio_client.messages.create(
        from_=WA_NUMBER,                 # env var already includes 'whatsapp:'
        to=f"whatsapp:{to_e164}",        # prefix only the recipient number
        body=body
    )

# ---------------------------
# WhatsApp inbound webhook
# ---------------------------
from flask import request, jsonify

@app.route("/wa/webhook", methods=["POST"])
def wa_webhook():
    """
    Twilio -> Smartie -> Twilio
    Expects x-www-form-urlencoded from Twilio's WhatsApp Sandbox/Number.
    """
    try:
        # 1) Read Twilio form fields safely
        from_num = (request.form.get("From") or "").replace("whatsapp:", "").strip()
        body     = (request.form.get("Body") or "").strip()

        if not from_num:
            # Bad payload from source; reply 400 but don't crash
            return jsonify({"error": "missing From"}), 400

        # 2) Route through Smartie brain
        user_id = f"wa:{from_num}"
        result  = route_message(user_id, body) or {}
        reply_text = result.get("reply", "Sorry — I didn’t quite catch that.")

        # 3) Send the reply back over WhatsApp (fire-and-forget)
        try:
            send_wa(from_num, reply_text)
        except Exception:
            # Log but still return 200/204 so Twilio doesn’t retry forever
            traceback.print_exc()

        # 4) MUST return a response to Twilio quickly (2xx)
        # 204 = No Content (OK)
        return ("", 204)

    except Exception as e:
        # Safety net: never let the endpoint crash
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ==================================================
# Web JSON endpoint (/smartie)
# ==================================================
def derive_user_id(req_json, flask_request):
    uid = (req_json or {}).get("user_id")
    if uid:
        return str(uid)
    raw = f"{flask_request.remote_addr}|{flask_request.headers.get('User-Agent','')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

@app.route("/smartie", methods=["POST"])
def smartie_reply():
    try:
        data = request.get_json() or {}
        user_input = data.get("message", "")
        user_id = derive_user_id(data, request)   # stable per user/device
        return jsonify(route_message(user_id, user_input))
    except Exception:
        traceback.print_exc()
        return jsonify({"reply": "Oops—something went wrong. Try again in a moment."}), 500


# ==================================================
# Run app (dev)
# ==================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

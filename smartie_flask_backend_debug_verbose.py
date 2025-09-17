# smartie_flask_backend_debug_verbose.py

import os
import hashlib
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from twilio.rest import Client
from datetime import datetime, timezone, timedelta

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
# Last time we saw each user (in-memory; resets on restart unless you persist it)
LAST_SEEN: dict[str, datetime] = {}
LAST_CONCERN: dict[str, dict] = {}  # { user_id: {"key": str, "stack": [pillars]} }

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

# 2) Concern → suggested pillars (extended matrix)
CONCERN_TO_PILLARS = {
    # Physical
    "cholesterol": ["nutrition","movement","environment"],
    "overweight": ["nutrition","movement","thoughts","environment"],
    "obese": ["nutrition","movement","thoughts","environment"],
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
    "copd": ["stress","movement","sleep","environment"],      # was “breathing”
    "asthma": ["stress","sleep","environment"],                # was “breathing”
    "sleep apnoea": ["sleep","nutrition","stress"],            # was “weight”
    "liver disease": ["nutrition","environment","stress"],
    "fatty liver": ["nutrition","movement","environment"],
    "kidney disease": ["nutrition","stress","movement"],
    "bone health": ["movement","nutrition","environment"],
    "osteoporosis": ["movement","nutrition","environment"],
    "osteopenia": ["movement","nutrition","environment"],
    "metabolic syndrome": ["nutrition","movement","sleep","stress"],
    "autoimmune disorder": ["stress","emotions","nutrition","sleep"],
    "rheumatoid arthritis": ["movement","stress","emotions"],
    "psoriasis": ["stress","emotions","social"],
    "multiple sclerosis": ["movement","emotions","social"],

    # Mental (ICD-11-ish)
    "low mood": ["sleep","movement","thoughts","social"],
    "depression": ["sleep","movement","thoughts","social"],
    "bipolar": ["sleep","stress","emotions","social"],
    "sad": ["sleep","thoughts","movement","social"],
    "anxiety": ["stress","thoughts","sleep","emotions"],
    "gad": ["stress","thoughts","sleep","emotions"],
    "ptsd": ["stress","emotions","social"],
    "stress": ["stress","thoughts","emotions"],
    "emotional dysregulation": ["emotions","thoughts","social"],
    "binge eating": ["nutrition","emotions","thoughts"],
    "adhd": ["environment","movement","sleep","thoughts"],     # “structure” -> environment
    "asd": ["social","environment","thoughts"],
    "gaming": ["environment","thoughts","movement"],
    "addiction": ["emotions","thoughts","social"],
    "insomnia": ["sleep","stress","environment"],
    "sleep disorder": ["sleep","stress","environment"],
    "cognitive decline": ["thoughts","social","movement"],
    "mild neurocognitive disorder": ["thoughts","movement","social"],
    "dementia": ["thoughts","social","environment"],
    "alzheimer": ["thoughts","social","movement"],

    # Gut
    "bloating": ["nutrition","emotions","stress"],
    "constipation": ["nutrition","movement","emotions"],
    "diarrhoea": ["nutrition","emotions","stress"],
    "functional gi": ["nutrition","emotions","stress"],
    "ibs": ["nutrition","stress","sleep","emotions"],
    "leaky gut": ["nutrition","emotions","stress"],
    "food allergy": ["nutrition","environment"],
    "food intolerance": ["nutrition","environment"],
    "gluten": ["nutrition","emotions"],
    "dairy": ["nutrition","emotions"],
    "wheat": ["nutrition","emotions"],
    "histamine": ["nutrition","emotions"],
    "gerd": ["nutrition","sleep","environment"],
    "acid reflux": ["nutrition","sleep","environment"],
    "crohn": ["nutrition","stress","emotions"],
    "ulcerative colitis": ["nutrition","stress","emotions"],
    "coeliac": ["nutrition","emotions","stress"],
    "autoimmune gastritis": ["nutrition","stress","emotions"],
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
You are Smartie, the eity20 coach: warm, brief, and practical. You help people make small, sustainable changes.

Focus areas (mention only when helpful):
• 8 pillars: Environment & Structure, Nutrition & Gut Health, Sleep, Exercise & Movement, Stress Management, Thought Patterns, Emotional Regulation, Social Connection.
• SMARTS: Sustainable, Mindful mindset, Aligned, Realistic, Train your brain, Speak up.
• eity20: 80% consistency, 20% flexibility, 100% human. Pareto mindset: small inputs → big outputs.

Response rules:
1) Start with ONE empathetic human line that reflects their words (no generic platitudes).
2) Ask at most ONE short clarifying question **only if needed** to tailor advice.
3) Give 2–3 tiny, time-bound steps (clear trigger, when, frequency). Keep under ~120 words total.
4) Tie advice to a pillar or SMARTS principle once (e.g., “(Pillar: Sleep)”).
5) Offer a next step when appropriate: “type *advice* for tips today” or “type *baseline* to prioritise pillars.”
6) Celebrate wins; normalise lapses; avoid moral language. No medical diagnosis. If crisis terms appear, advise urgent help.
7) Use plain language; no jargon; no lists of caveats.

Style: warm, encouraging, concrete, and human. Never mention you are an AI or a model.
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

# Short, consistent eity20 intro used on first contact + concern-first replies
EITY20_INTRO = (
    "I’m Smartie — your supportive eity20 friend. "
    "eity20 links physical, mental, and gut health through 8 pillars "
    "(Environment, Nutrition, Sleep, Movement, Stress, Thoughts, Emotions, Social) "
    "and SMARTS change: Sustainable, Mindful mindset, Aligned, Realistic, "
    "Train your brain, Speak up."
)

# Human-readable labels for concerns (what we show to the user)
HUMAN_LABELS = {
    "cholesterol": "high cholesterol",
    "weight": "weight / GLP-1 use",
    "blood sugar": "type 2 diabetes / blood sugar",
    "menopause": "menopause",
    "blood pressure": "high blood pressure",
    "joint": "joint pain / osteoarthritis",
    "cvd": "heart rhythm / cardiovascular risk",
    "breathing": "breathing & sleep (COPD / asthma / sleep apnoea)",
    "liver": "liver health",
    "kidney": "kidney health",
    "bone": "bone health (osteopenia / osteoporosis)",
    "metabolic": "metabolic syndrome",
    "autoimmune": "autoimmune condition",
    "low mood": "low mood / depression",
    "anxiety": "anxiety",
    "ptsd": "stress / PTSD",
    "emotional eating": "emotional / binge eating",
    "adhd": "ADHD",
    "sleep": "sleep problems",
    "cognitive": "thinking / memory",
    "ibs": "IBS / gut symptoms",
    "reflux": "acid reflux / GERD",
    # fallback keys will be title-cased if not present
}

# Tailored leading questions by concern label (used right after the intro)
LEADING_QUESTIONS = {
    # Physical
    "cholesterol": "What do you think has driven your cholesterol up lately — food choices, weight, family history, or something else?",
    "weight": "What makes losing weight so tough right now — hunger, evening snacking, routine, or energy for movement?",
    "blood sugar": "What do you think most affects your blood sugar — meal timing, carb type/size, activity, or sleep/stress?",
    "menopause": "Which symptom bothers you most — sleep, hot flushes, mood, or weight changes?",
    "blood pressure": "When is your blood pressure highest — stressful days, poor sleep, salty foods, or inactivity?",
    "joint": "Which joints limit you most and when — mornings, after sitting, or with activity?",
    "cvd": "What feels most important to work on first — movement, food quality, blood pressure, or stress?",
    "breathing": "What tends to trigger symptoms — exertion, allergens, sleep position, or stress?",
    "liver": "Which area do you want to focus on — alcohol, weight, balanced meals, or daily movement?",
    "kidney": "What’s your current priority — blood pressure control, blood sugars, protein balance, or salt intake?",
    "bone": "Which change feels most doable — strength exercises, calcium/protein at meals, or vitamin D checks?",
    "metabolic": "Which piece feels most moveable first — waist size, triglycerides, fasting glucose, or blood pressure?",
    "autoimmune": "What tends to cause a flare up — stress, poor sleep, infections, or specific foods?",

    # Mental
    "low mood": "What shifts your mood most — sleep quality, activity, social contact, or self-talk?",
    "anxiety": "When does anxiety spike — mornings, social settings, at night, or after caffeine/sugar?",
    "ptsd": "What’s your main stress load — work, caring, finances, health, or something else?",
    "emotional eating": "What’s the usual pattern before eating episodes — strong feelings, tiredness, being unprepared, or restrictive rules?",
    "adhd": "What do you think will help — routines, sleep, food planning, or focus breaks?",
    "addiction": "What’s the main trigger — boredom, late-night routine, stress, or social cues?",
    "sleep": "Which part is hardest — getting to sleep, staying asleep, wake time, or caffeine timing?",
    "cognitive": "Which daily function needs the most help — remembering tasks, planning, or staying focused?",

    # Gut
    "ibs": "What most sets symptoms off — certain foods, stress spikes, poor sleep, or irregular meals?",
    "functional gi": "What’s most noticeable — bloating, pain, constipation, diarrhoea, or post-meal fatigue?",
    "autoimmune gi": "What tends to precede flare ups — stress, infections, specific foods, or inconsistent meds?",
    "food intolerance": "Which foods are you most suspicious of right now?",
    "reflux": "When is reflux worst — late meals, lying down after eating, trigger foods, or larger portions?",
}

# Map many user phrases to one canonical concern key
CONCERN_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("cholesterol","hyperlipid","dyslipid"), "cholesterol"),
    (("overweight","obese","weight","weight loss","glp-1","ozempic","wegovy","mounjaro","tirzepatide","semaglutide"), "weight"),
    (("type 2 diabetes","t2d","prediabetes","pre-diabetes","blood sugar","insulin resistance"), "blood sugar"),
    (("hypertension","high blood pressure","blood pressure"), "blood pressure"),
    (("menopause","perimenopause","peri-menopause"), "menopause"),
    (("osteoarthritis","arthritis","joint pain"), "joint"),
    (("coronary heart disease","chd","atrial fibrillation","afib","a-fib"), "cvd"),
    (("copd","asthma","sleep apnoea","sleep apnea","breathing difficulties"), "breathing"),
    (("liver disease","nafld","fatty liver","arld"), "liver"),
    (("ckd","kidney disease"), "kidney"),
    (("osteopenia","osteoporosis","bone health"), "bone"),
    (("metabolic syndrome","high triglycerides","low hdl","large waist","waist circumference"), "metabolic"),
    (("autoimmune","ms","multiple sclerosis","graves","type 1 diabetes","rheumatoid arthritis","psoriasis","vasculitis"), "autoimmune"),
    (("low mood","depression","bipolar","sad","seasonal affective"), "low mood"),
    (("anxiety","gad","generalised anxiety","generalized anxiety"), "anxiety"),
    (("ptsd","post-traumatic stress"), "ptsd"),
    (("binge eating","binge-eating","emotional eating","comfort eating","eating disorder","bed"), "emotional eating"),
    (("adhd","attention deficit","asd","autism","neurodevelopmental"), "adhd"),
    (("sleep-wake","circadian","insomnia","sleep disorder"), "sleep"),
    (("mci","cognitive decline","neurocognitive","dementia","alzheimer"), "cognitive"),
    (("ibs","irritable bowel"), "ibs"),
    (("reflux","gerd","acid reflux"), "reflux"),
]

def match_concern_key(text: str) -> str | None:
    """Return the canonical concern key from user text, or None."""
    t = (text or "").lower()
    for aliases, key in CONCERN_ALIASES:
        if any(a in t for a in aliases):
            return key
    return None

def human_label_for(key: str) -> str:
    return HUMAN_LABELS.get(key, key.title())

def leading_question_for(key: str) -> str:
    return LEADING_QUESTIONS.get(
        key, f"What do you think is contributing most to your {human_label_for(key)} right now?"
    )

def make_concern_intro_reply(concern_key: str, stack: list[str], user_text: str | None = None) -> str:
    """
    Warm intro for priority concerns:
    - 1 empathetic line
    - brief eity20 framing
    - show best starting pillar (+ next pillars)
    - 1 tailored leading question
    - clear choice: advice vs baseline
    """
    # human labels + pillar labels
    concern_label = human_label_for(concern_key)
    label_map = {k: v["label"] for k, v in PILLARS.items()}
    first = stack[0]
    first_label = label_map.get(first, first.title())
    rest_labels = [label_map.get(p, p.title()) for p in stack[1:]]
    rest_part = f" Next up: {', '.join(rest_labels)}." if rest_labels else ""

    # 1) Empathetic opener (short, human, mirrors their concern)
    opener = f"I hear you — {concern_label} can feel tough. Let’s keep this simple and doable."

    # 2) Micro eity20 framing (one line)
    framing = ("We’ll use eity20’s pillars to make small changes with big impact "
               "(80% consistent, 20% flexible — 100% human).")

    # 3) Leading question (tailored)
    leading_q = leading_question_for(concern_key)

    # 4) Clear choice
    choice = (
        "Would you like me to:\n"
        "• **Share focused advice** for today (type: *advice*)\n"
        "• **Do a 1-minute baseline** to prioritise your pillars (type: *baseline*)"
    )

    return (
        f"{opener}\n\n"
        f"{framing}\n\n"
        f"For *{concern_label}*, the best place to start is **{first_label}**.{rest_part}\n\n"
        f"{leading_q}\n\n"
        f"{choice}"
    )

# ==================================================
# Unified router
# ==================================================
def route_message(user_id: str, text: str) -> dict:
    lower = (text or "").strip().lower()
    tag = f"\n{EITY20_TAGLINE}" if 'EITY20_TAGLINE' in globals() else ""

    # --- 0) Greeting logic (first-time + returning after 24h) ---
    now = datetime.now(timezone.utc)
    last = LAST_SEEN.get(user_id)

    # First ever message from this user
    if last is None:
        LAST_SEEN[user_id] = now
        intro = (
            "Hello, I'm Smartie. I am here to help you stay eity20 — "
            "80% consistent, 20% flexible, 100% human.
            "How would you like me to support your health & wellbeing journey?:\n\n"
            "• Type a **health concern** (e.g. cholesterol, depression, IBS)\n"
            "• Type a **lifestyle area** (sleep, nutrition, movement, stress)\n"                
            "• Type **advice** for general tips\n"
            "• Type **baseline** for a 1-minute assessment\n\n"
            f"{EITY20_TAGLINE}"
        )
        return {"reply": intro}

    # Returning user: greet if it's been 24h since last message OR if they explicitly say hi
    long_gap = (now - last) >= timedelta(hours=24)
    said_hello = lower in {"hi", "hello", "hey", "hi smartie", "hello smartie"}
    if long_gap or said_hello:
        LAST_SEEN[user_id] = now
        return {"reply": "Hello, welcome back. How are you today?"}

    # --- 1) Safety first ---
    s = safety_check_and_reply(text)
    if s:
        LAST_SEEN[user_id] = now
        return {"reply": s}

    # --- 2) Quick commands: tracking ---
    if lower in {"done", "i did it", "check in", "check-in", "log done", "logged"}:
        _ = log_done(user_id=user_id)
        g = get_goal(user_id)
        LAST_SEEN[user_id] = now
        if g:
            return {"reply": (
                "Nice work — logged for today! ✅\n"
                f"Goal: “{g.text}” ({g.cadence})\n"
                "Say **progress** to see the last 14 days."
            ) + tag}
        return {"reply": "Logged! If you want this tied to a goal, run **baseline** to set one." + tag}

    if lower in {"progress", "summary", "stats"}:
        LAST_SEEN[user_id] = now
        return {"reply": tracker_summary(user_id) + tag}

    if lower in {"history", "recent"}:
        logs = last_n_logs(user_id, 5)
        LAST_SEEN[user_id] = now
        if not logs:
            return {"reply": "No check-ins yet. Say **done** whenever you complete your goal today." + tag}
        lines = ["Recent check-ins:"] + [f"• {e.date.isoformat()}" for e in logs]
        return {"reply": "\n".join(lines) + tag}

    if lower in {"what's my goal", "whats my goal", "goal", "show goal"}:
        g = get_goal(user_id)
        LAST_SEEN[user_id] = now
        if g:
            return {"reply": f"Your goal is: “{g.text}” (cadence: {g.cadence}, pillar: {g.pillar_key})." + tag}
        return {"reply": "You don’t have an active goal yet. Type **baseline** to set one." + tag}

    # --- Human-first: offer simple options for first/open-ended asks ---
    OPEN_ENDED_TRIGGERS = {
        "help", "advice", "support",
        "change my lifestyle", "change my life",
        "improve my lifestyle", "get healthier",
        "where do i start", "how do i start",
        "lifestyle changes", "improve my health",
    }        

    if any(phr in lower for phr in OPEN_ENDED_TRIGGERS):
        LAST_SEEN[user_id] = now
        reply = (
            "I’m here to support you. Let’s see how I can help:\n\n"
            "1) **Health concern** (physical, mental, or gut)\n"
            "   • Type your concern — e.g. *cholesterol*, *depression*, *IBS*.\n\n"
            "2) **Lifestyle concern**\n"
            "   • Type a pillar area — e.g. *sleep*, *nutrition*, *movement*, *stress*.\n\n"
            "3) **General quick tips**\n"
            "   • Type **advice**.\n\n"
            "4) **Baseline assessment (1 minute)**\n"
            "   • Type **baseline** to prioritise the pillars to focus on.\n\n"
            f"{EITY20_TAGLINE}"
        )
        return {"reply": reply}
    
    # --- 3) Concern-first: introduce Smartie/eity20, ask, and offer choice ---
    stack = detect_priority_stack(text)
    if stack:
        key = match_concern_key(text) or "blood sugar"  # sensible default
        reply = make_concern_intro_reply(key, stack, user_text=text)

        # remember this so the next "advice" message knows what to use
        LAST_CONCERN[user_id] = {"key": key, "stack": stack}
        LAST_SEEN[user_id] = now
        return {"reply": reply + tag}
    
    # If the user chooses after a concern-first intro
    if lower == "advice":
        saved = LAST_CONCERN.get(user_id)
        first_pillar = (saved["stack"][0] if saved and saved.get("stack") else "nutrition")
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply(first_pillar, text) + tag}

    if lower == "baseline":
        # (optional) clear the saved concern so baseline can take over
        LAST_CONCERN.pop(user_id, None)
        bl = handle_baseline(user_id, text)
        if bl is not None:
            LAST_SEEN[user_id] = now
            return bl

    # --- 4) Onboarding / Baseline / Set a SMARTS goal ---
    if lower in {"start", "get started", "baseline", "onboard", "begin"}:
        bl = handle_baseline(user_id, text)   # asks concern → 8 ratings → suggest pillar → set goal
        if bl is not None:
            LAST_SEEN[user_id] = now
            return bl

    # Continue baseline if mid-session
    bl = handle_baseline(user_id, text)
    if bl is not None:
        LAST_SEEN[user_id] = now
        return bl

    # --- 5) Pillar advice (direct keywords → playbook) ---
    if any(k in lower for k in ["environment", "structure", "routine", "organise", "organize"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("environment", text)}

    if any(k in lower for k in ["nutrition", "gut", "food", "diet", "ibs", "bloating"]):
        if any(k in lower for k in NUTRITION_RULES_TRIGGERS):
            LAST_SEEN[user_id] = now
            return {"reply": nutrition_rules_answer()}
        if any(k in lower for k in FOODS_TRIGGERS):
            LAST_SEEN[user_id] = now
            return {"reply": nutrition_foods_answer()}
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("nutrition", text)}

    if any(k in lower for k in ["sleep", "insomnia", "tired", "can't sleep", "cant sleep"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("sleep", text)}

    if any(k in lower for k in ["exercise", "movement", "workout", "walk", "steps"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("movement", text)}

    if any(k in lower for k in ["stress", "stressed", "anxiety", "anxious", "overwhelmed"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("stress", text)}

    if any(k in lower for k in ["thought", "mindset", "self-talk", "self talk", "motivation"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("thoughts", text)}

    if any(k in lower for k in ["emotion", "feelings", "craving", "urge", "binge", "comfort eat", "comfort-eat"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("emotions", text)}

    if any(k in lower for k in ["social", "connection", "friends", "lonely", "isolation", "isolated"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("social", text)}

    # --- 6) Intent/concern mapper → pillar → playbook (support mode) ---
    pillar = map_intent_to_pillar(text)
    if pillar:
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply(pillar, text)}

    pillars = suggest_pillars_for_concern(text)
    if pillars:
        labels = [PILLARS[p]["label"] for p in pillars if p in PILLARS]
        suggestion = ", ".join(labels[:3]) or ", ".join(pillars[:3])
        LAST_SEEN[user_id] = now
        return {"reply": (
            f"Thanks — that helps focus the right areas. These pillars usually help most: {suggestion}.\n"
            f"Want to do a 1-minute baseline and pick one to start?\n{EITY20_TAGLINE}"
        )}

    # --- 7) OpenAI fallback (short, warm, actionable, 80/20 tone) ---
    sd = style_directive(text)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SMARTIE_SYSTEM_PROMPT},
            {"role": "user", "content": f"{sd}\n\nUser: {text}"},
        ],
        max_tokens=420,
        temperature=0.75,
    )
    LAST_SEEN[user_id] = now
    return {"reply": resp.choices[0].message.content.strip() + tag}

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

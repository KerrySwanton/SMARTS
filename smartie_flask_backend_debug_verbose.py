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
# Last conversational state per user (simple finite-state store)
# e.g. STATE[user_id] = {"await": "advice_topic"} or {"await": "programme_confirm"}
# Simple per-user state (mini state machine)
STATE: dict[str, dict] = {}   # { user_id: {"await": "advice_topic"} }

def get_state(uid: str) -> dict:
    return STATE.get(uid, {})

def set_state(uid: str, **data) -> None:
    STATE[uid] = dict(data)

def clear_state(uid: str) -> None:
    STATE.pop(uid, None)
    
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

# Always add the 80/20 closer if missing
EITY20_REMINDER = "Aim for 80% consistency, 20% flexibility — 100% human."

def ensure_eity20_reminder(text: str) -> str:
    t = (text or "").strip()
    if EITY20_REMINDER.lower() in t.lower():
        return t
    if t.endswith(("!", "?", ".")):
        return t + "\n\n" + EITY20_REMINDER
    return t + "\n\n" + EITY20_REMINDER

# --- Advice intent (first-contact) -------------------------------------------
ADVICE_INTENT_TERMS = {
    "advice", "help", "support",
    "can you help", "can you help me",
    "i need help", "i'd like some advice", "i would like some advice",
    "improve my lifestyle", "change my lifestyle",
    "get healthier", "where do i start",
    "how do i change my behaviour", "how to change my behavior", "change my behaviour", "change my behavior",
}

def is_advice_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in ADVICE_INTENT_TERMS)

def advice_opening_message() -> str:
    return (
        "Hello, I would be very happy to help you.\n\n"
        "When it comes to changing behaviour, it’s the small, consistent inputs that create the biggest long-term change. "
        "The eity20 ethos is 80% consistency, 20% flexibility because we are 100% human.\n\n"
        "We’ll use the **SMARTS** approach to guide you:\n"
        "• **Sustainable** — keep changes doable day to day\n"
        "• **Mindful mindset** — notice patterns without judgment\n"
        "• **Aligned** — match goals to what matters to you\n"
        "• **Realistic** — start small and build gradually\n"
        "• **Train your brain** — repeat tiny habits until they stick\n"
        "• **Speak up** — sharing goals/support makes change easier\n\n"
        "Is there someone specific you would like advice about?\n"
        "If it’s for you, we can start with a focus like sleep, nutrition, movement, or stress — or I can suggest a few simple first steps."
    )

# 5) System prompt for the fallback
SMARTIE_SYSTEM_PROMPT = """
You are Smartie, the eity20 coach: warm, brief, and practical. You help people make small, sustainable changes.

Focus areas (mention only when helpful):
- 8 pillars: Environment & Structure, Nutrition & Gut Health, Sleep, Exercise & Movement, Stress Management, Thought Patterns, Emotional Regulation, Social Connection.
- SMARTS: Sustainable, Mindful mindset, Aligned, Realistic, Train your brain, Speak up.
- eity20: 80% consistency, 20% flexibility, 100% human. Pareto mindset -> small inputs = big outputs.

Response rules:
1. Start with one empathetic human line that reflects their words (no generic platitudes).
2. Ask at most one short clarifying question only if needed to tailor advice.
3. Give 2-3 tiny, time-bound steps (clear trigger, when, frequency).
4. Tie advice to a pillar or SMARTS principle once (e.g., "(Pillar: Sleep)").
5. Offer a next step when appropriate: "type *advice* for tips today" or "type *baseline* to prioritise pillars."
6. Celebrate wins; normalise lapses; avoid moral language. No medical diagnosis. If crisis terms appear, advise urgent help.
7. Use plain language; no jargon; no lists of caveats.

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
    "worry": "worry",
    "ptsd": "stress / PTSD",
    "stress": "stress",
    "emotional eating": "emotional / binge eating",
    "emotions": "emotional regulation",
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
    """Return a human-friendly label for a concern key, with fallback."""
    if not key:
        return ""
    return HUMAN_LABELS.get(key, key.replace("_", " ").title())

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
    - clear choices (advice/programme/goal)
    - pillar-specific outcomes line
    """
    # human labels + pillar labels
    concern_label = human_label_for(concern_key)
    label_map = {k: v["label"] for k, v in PILLARS.items()}
    first = stack[0]
    first_label = label_map.get(first, first.title())
    rest_labels = [label_map.get(p, p.title()) for p in stack[1:]]
    rest_part = f" Next up: {', '.join(rest_labels)}." if rest_labels else ""

    # 1) Empathetic opener
    opener = (
        f"Thank you — {concern_label} can feel tough. "
        "Let’s make small, doable changes so you can feel better and thrive."
    )

    # 2) Micro eity20 framing
    framing = ("We’ll use eity20’s pillars with SMARTS (Sustainable, Mindful mindset, Aligned, "
               "Realistic, Train your brain, Speak up) — 80% consistent, 20% flexible, 100% human.")

    # 3) Leading question (tailored)
    leading_q = leading_question_for(concern_key)

    # 4) Options up-front (programme included; direct goal path)
    programme_hint = f"the eity20 programme for *{first_label}*"
    choices = (
        "Here are good next steps:\n"
        "1) **Tell me more** — what do you think is driving this right now?\n"
        f"2) **Start {programme_hint}** to see what it covers.\n"
        "3) **Get helpful advice** — say *general tips* and I can share practical suggestions.\n"
        f"4) **Set a SMARTS goal** for {first_label.lower()} — type *goal*.\n"
        "5) **Not sure where to begin?** Type *baseline* for a 1-minute assessment to prioritise your pillars."
    )

    # 5) Pillar-specific outcomes (ties benefits explicitly)
    outcomes = PILLAR_OUTCOMES.get(first, "")

    return (
        f"{opener}\n\n"
        f"{framing}\n\n"
        f"For *{concern_label}*, the best place to start is **{first_label}**.{rest_part}\n\n"
        f"{leading_q}\n\n"
        f"{choices}\n\n"
        f"{outcomes}"
    )

# --- Advice "programs" config (must be above route_message) ---

PROGRAMS = {
    "anxiety":    {"label": "reduce anxiety",            "pillar": "stress"},
    "emotions":   {"label": "regulate your emotions",    "pillar": "emotions"},
    "sleep":      {"label": "sleep better",              "pillar": "sleep"},
    "nutrition":  {"label": "eat for steady energy",     "pillar": "nutrition"},
    "movement":   {"label": "move more, feel better",    "pillar": "movement"},
}

# Map many user words to one program key
PROGRAM_ALIASES = [
    (("anxiety","anxious","worry","worries","worrying","panic"),                        "anxiety"),
    (("emotion","emotions","urge","craving","binge","comfort eat","comfort-eat"),       "emotions"),
    (("sleep","insomnia","can't sleep","cant sleep","tired","wake"),                    "sleep"),
    (("food","nutrition","diet","snack","snacking","eat","eating","ibs"),               "nutrition"),
    (("exercise","move","movement","walk","steps","workout"),                           "movement"),
]

def detect_program_key(text: str) -> str | None:
    t = (text or "").lower()
    for aliases, key in PROGRAM_ALIASES:
        if any(w in t for w in aliases):
            return key
    return None

def program_pitch(key: str) -> str:
    p = PROGRAMS.get(key)
    if not p:
        return ""
    return f"an eity20 programme to **{p['label']}** (Pillar: {p['pillar'].title()})"

# Quick checks for “start a programme” intent
START_WORDS   = ("start","begin","try","do","kick off","start a","begin a")
PROGRAM_WORDS = ("programme","program","plan","course")

def wants_program_start(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in START_WORDS) and any(p in t for p in PROGRAM_WORDS)

# Infer program topic from free text (used when user says “start …”)
def detect_topic_from_text(text: str) -> str | None:
    t = (text or "").lower()
    k = detect_program_key(t)
    if k:
        return k
    # small safety nets
    if "ibs" in t or "gut" in t or "reflux" in t:
        return "nutrition"
    if "worry" in t or "worrying" in t or "panic" in t:
        return "anxiety"
    return None

# Build the program→pillar map (now that PROGRAMS exists)
TOPIC_TO_PILLAR = {k: v["pillar"] for k, v in PROGRAMS.items()}

def start_baseline_now(user_id: str, text: str, now: datetime):
    # 1) Try to seed baseline with the user’s last concern/topic or this message
    seed_key = None
    saved = LAST_CONCERN.get(user_id)
    if saved:
        seed_key = saved.get("key") or saved.get("topic")
    seed_key = seed_key or match_concern_key(text)

    # 2) Clear context so baseline owns the conversation
    LAST_CONCERN.pop(user_id, None)
    STATE.pop(user_id, None)

    # 3) Start baseline (prefer new signature; fall back if older handle_baseline)
    try:
        bl = handle_baseline(user_id, text, seed_concern_key=seed_key)  # preferred
    except TypeError:
        preface = f"Great — we’ll keep *{human_label_for(seed_key)}* in mind.\n\n" if seed_key else ""
        bl = preface + (handle_baseline(user_id, text) or "")

    if bl is not None:
        LAST_SEEN[user_id] = now
        # Normalize to the router’s shape
        return bl if isinstance(bl, dict) else {"reply": bl}

    # If nothing came back, provide a nudge
    return {"reply": "Okay — type *baseline* to begin the 1-minute assessment."}

# --- Pillar-specific clarifier ------------------------------------------------
RELATED_CONCERNS_BY_PILLAR = {
    "sleep":     ["stress/anxiety", "blood sugar / type 2 diabetes", "reflux/GERD", "sleep apnoea", "low mood"],
    "nutrition": ["IBS/bloating", "blood sugar / type 2 diabetes", "cholesterol", "reflux/GERD", "weight"],
    "movement":  ["joint pain/arthritis", "low mood", "weight", "blood pressure", "sleep issues"],
    "stress":    ["anxiety/GAD", "PTSD/trauma", "blood pressure", "IBS/gut symptoms", "sleep problems"],
    "thoughts":  ["low mood/depression", "anxiety", "insomnia", "binge/emotional eating"],
    "emotions":  ["binge/emotional eating", "anxiety", "sleep problems", "stress-related flare ups"],
    "environment": ["ADHD/routine", "screen overuse", "snacking cues", "sleep timing"],
    "social":    ["loneliness", "low mood", "motivation", "stress"],
}

def related_concerns_for_pillar(pillar: str) -> str:
    items = RELATED_CONCERNS_BY_PILLAR.get(pillar, [])
    return ", ".join(items[:5])

PILLAR_OUTCOMES = {
    "sleep": (
        "Better sleep can lift your mood, sharpen focus, improve memory, balance blood sugar, "
        "reduce cravings, support immunity, help manage weight and improve energy."
    ),
    "nutrition": (
        "Improving nutrition can ease gut issues, balance blood sugar, "
        "reduce inflammation, improve bone health, reduce risk of chronic diseases, boost energy, and support brain health."
    ),
    "movement": (
        "Moving more can reduce stress and anxiety, improve sleep, reduce risk of chronic diseases like type 2 diabetes, "
        "boost mood, ease joint pain, and increase energy."
    ),
    "stress": (
        "Managing stress can reduce anxiety, improve sleep, lower blood pressure, "
        "calm digestion, improve mental clarity and strengthen your resilience."
    ),
    "thoughts": (
        "Changing thought patterns can boost mood, regulate emotions, "
        "reduce stress and anxiety, lift self-esteem, reduce inflammation, "
        "and support healthier habits."
    ),
    "emotions": (
        "Regulating emotions can improve relationships, reduce stress, "
        "stabilise mood, cut down emotional eating, and support mental clarity."
    ),
    "environment": (
        "Shaping your environment can make healthy habits easier, reduce distractions, "
        "improve sleep routines, improve your mood, increase motivation, lower stress and improve your overall health."
    ),
    "social": (
        "Strengthening social connections can lift mood, reduce loneliness, "
        "increase motivation, protect heart health, improve immunity and build resilience."
    ),
}

def pillar_detail_prompt(pillar: str) -> str:
    human = PILLARS.get(pillar, {}).get("label", pillar.title())
    related = related_concerns_for_pillar(pillar)
    programme_hint = f"the eity20 programme for *{human}*"
    return (
        f"Let’s focus on *{human}*.\n\n"
        f"Is there a reason you want help with this? For some people it’s linked to a health concern such as {related}.\n\n"
        f"Here are a few ways we can continue:\n"
        f"1) If it’s due to a health concern, just name it (e.g., “type 2 diabetes”, “IBS”).\n"
        f"2) Start {programme_hint} to see what the programme covers.\n"
        f"3) If you’d like suggestions, say **general tips** and I can share some helpful advice with you.\n"
        f"4) Set a SMARTS goal for {human.lower()} — just type *goal*.\n\n"
        f"{PILLAR_OUTCOMES.get(pillar, '')}"
    )

# --- Advice intent (first-contact) -------------------------------------------
ADVICE_INTENT_TERMS = {
    "advice", "help", "support",
    "can you help", "can you help me",
    "i need help", "i'd like some advice", "i would like some advice",
    "improve my lifestyle", "change my lifestyle", "get healthier", "where do i start",
    "how do i change my behaviour", "how to change my behavior", "change my behaviour", "change my behavior",
}

def is_advice_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in ADVICE_INTENT_TERMS)

def advice_opening_message() -> str:
    return (
        "Hello, I would be very happy to help you.\n\n"
        "When it comes to changing behaviour, it’s the small, consistent inputs that create the biggest long-term change. "
        "The eity20 ethos is 80% consistency, 20% flexibility — 100% human.\n\n"
        "We’ll use **SMARTS** to guide you: Sustainable, Mindful mindset, Aligned, Realistic, Train your brain, Speak up.\n\n"
        "Is there someone specific you would like advice about? "
        "If it’s for you, tell me your focus (e.g., sleep, nutrition, movement, stress) or say **baseline** to set a SMARTS goal."
    )

# ==================================================
# Unified router
# ==================================================
def route_message(user_id: str, text: str) -> dict:
    lower = (text or "").strip().lower()
    now = datetime.now(timezone.utc)
    tag = f"\n\n{EITY20_TAGLINE}" if 'EITY20_TAGLINE' in globals() else ""

    # --- A) First-message fast-path: if the user already asked for something, skip the intro
    first_time = user_id not in LAST_SEEN
    if first_time:
        # direct commands
        if lower in {"advice", "tip", "tips"}:
            set_state(user_id, **{"await": "advice_topic"})
            LAST_SEEN[user_id] = now
            return {"reply": (
                "What advice would you like?\n"
                "You can say things like: worry/anxiety, sleep, food/nutrition, movement, low mood, IBS — "
                "or another topic in your own words.\n\n"
                "If you’re unsure, you can also type *baseline*."
            )}

        if lower in {"baseline", "start baseline", "start-baseline"}:
            # (this is your existing direct-baseline block)
            return start_baseline_now(user_id, text, now)  # helper wrapper you already have

        # NEW: advice-like first message → show the warm advice opening (skip intro)
        if is_advice_intent(text):
            LAST_SEEN[user_id] = now
            return {"reply": advice_opening_message()}
        
        # 1) health concern keywords (e.g., “cholesterol”, “ibs”, “type 2 diabetes”)
        concern_key = match_concern_key(text)
        if concern_key:
            stack = detect_priority_stack(text) or [concern_key]
            LAST_CONCERN[user_id] = {"key": concern_key, "stack": stack}
            LAST_SEEN[user_id] = now
            return {"reply": make_concern_intro_reply(concern_key, stack, user_text=text) + tag}

        # 2) lifestyle area mapping
        pillar = map_intent_to_pillar(text)
        if pillar:
            set_state(user_id, **{"await": "pillar_detail", "pillar": pillar})
            LAST_SEEN[user_id] = now
            return {"reply": pillar_detail_prompt(pillar)}

    # 0) Greeting / welcome-back
    last = LAST_SEEN.get(user_id)
    if last is None:
        LAST_SEEN[user_id] = now
        intro = (
            "Hello, I'm Smartie. I am here to help you stay eity20 — "
            "80% consistent, 20% flexible, 100% human.\n\n"
            "How would you like me to support your health & wellbeing journey?\n\n"
            "• Type a *health concern* (e.g. cholesterol, depression, IBS)\n"
            "• Type a *lifestyle area* (sleep, nutrition, movement, stress)\n"
            "• Type *advice* for general tips\n"
            "• Type *baseline* for a 1-minute assessment\n\n"
            "Aim for 80% consistency, 20% flexibility — 100% human."
        )
        return {"reply": intro}

    long_gap = (now - last) >= timedelta(hours=24)
    said_hello = lower in {"hi", "hello", "hey", "hi smartie", "hello smartie"}
    if long_gap or said_hello:
        LAST_SEEN[user_id] = now
        return {"reply": (
            "Welcome back 👋\n\n"
            "Remember, eity20 is about staying 80% consistent, 20% flexible — 100% human.\n\n"
            "What’s on your mind today — a health concern, a lifestyle habit, or would you like some advice?"
        )}

    # 1) Safety first
    s = safety_check_and_reply(text)
    if s:
        LAST_SEEN[user_id] = now
        return {"reply": s}

    # --- X) Free-form: “start a … programme” (no menu needed) ---
    if wants_program_start(text):
        # infer topic (e.g., "anxiety", "sleep", "nutrition", "movement")
        topic = detect_topic_from_text(text) or "nutrition"
        pillar = (
            TOPIC_TO_PILLAR.get(topic)
            or map_intent_to_pillar(topic)
            or "nutrition"
        )
    
        # remember for follow-ups
        LAST_CONCERN[user_id] = {"topic": topic}
    
        # human-friendly label, e.g. “an eity20 programme to reduce anxiety”
        pitch = program_pitch(topic) or f"an eity20 programme for *{topic}*"
    
        safety = (
            "Heads-up: this isn’t a medical diagnostic service. "
            "eity20 supports health & wellbeing via lifestyle change."
        )
    
        LAST_SEEN[user_id] = now
        return {"reply": (
            f"Brilliant — let’s begin {pitch}.\n"
            f"{safety}\n\n"
            + compose_reply(pillar, f"start programme: {topic}")
        )}
    
    # 2) Tracking quick commands
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

    # 2.x Direct commands: advice / baseline (run early)
    cmd = lower.strip()

    # ---- Advice flow (mini state machine) ----
    if cmd in {"advice", "tips", "tip"}:
        STATE[user_id] = {"await": "advice_topic"}
        LAST_SEEN[user_id] = now
        return {"reply": (
            "What advice would you like?\n\n"
            "You can say things like: worry/anxiety, sleep, food/nutrition, movement, low mood, IBS — "
            "or another topic in your own words.\n\n"
            "If you’re unsure, you can also type *baseline*."
        )}

    waiting = STATE.get(user_id, {}).get("await")
    if waiting == "advice_topic":
        topic_key = detect_program_key(text)
        if not topic_key:
            LAST_SEEN[user_id] = now
            return {"reply": (
                "Thank you. Tell me in a few words what you would like help with "
                "(e.g., anxiety, sleep, food, movement, IBS). Or type *baseline* if you’re not sure."
            )}
    
        STATE.pop(user_id, None)                         # clear state
        LAST_CONCERN[user_id] = {"topic": topic_key}     # <— REMEMBER the chosen topic
    
        pitch = program_pitch(topic_key)
        LAST_SEEN[user_id] = now
        return {"reply": (
            f"Great — we can focus on *{topic_key}*.\n\n"
            "What would you like to do next?\n"
            f"1) Start {pitch}\n"
            "2) Do a quick *baseline* to prioritise what matters most\n"
            "3) Get *general advice* on this topic\n\n"
            "Reply with **1**, **2**, or **3**."
        )}

    if cmd in {"1", "2", "3"}:
        saved = LAST_CONCERN.get(user_id, {})
        topic = saved.get("topic")
    
        # If we don't know the topic yet, ask for it first
        if not topic and cmd in {"1", "3"}:
            STATE[user_id] = {"await": "advice_topic"}
            LAST_SEEN[user_id] = now
            return {"reply": (
                "Tell me the topic in a few words (e.g., anxiety, sleep, food, movement, IBS) "
                "so I can tailor this for you."
            )}

        if cmd == "2":
            # Baseline path (use the unified helper that normalises outputs)
            return start_baseline_now(user_id, text, now)

        # Route topic → pillar for 1 or 3
        pillar = TOPIC_TO_PILLAR.get(topic) or map_intent_to_pillar(topic) or "stress"

        if cmd == "1":
            # Start programme: short intro + two tiny, time-bound steps via your playbook
            safety = ("(Heads-up: this isn’t a medical diagnostic service. "
                      "eity20 helps people improve health & wellbeing through lifestyle change.)")
            LAST_SEEN[user_id] = now
            return {"reply": (
                f"Brilliant – let’s begin {program_pitch(topic)}.\n"
                f"{safety}\n\n"
                + compose_reply(pillar, f"start programme: {topic}")
            )}

        if cmd == "3":
            # General advice on this topic (same engine, just without the programme preamble)
            LAST_SEEN[user_id] = now
            return {"reply": (
                "Here are two tiny actions you can try today 👇\n"
                f"(Pillar: {pillar.title()})\n\n"
                + compose_reply(pillar, f"general advice: {topic}")
            )}
    
    # ------------------------------------------------------------
    #  A) Direct command: BASELINE (run early)
    # ------------------------------------------------------------
    cmd = (text or "").strip().lower()
    if cmd in {"baseline", "start baseline", "start-baseline"}:
        # 1) Try to seed baseline with user's concern, if we have one
        seed_key = None
        saved = LAST_CONCERN.get(user_id)  # read BEFORE clearing
        if saved:
            seed_key = saved.get("key") or saved.get("topic")
        seed_key = seed_key or match_concern_key(text)
    
        # 2) Clear context so baseline owns the conversation
        LAST_CONCERN.pop(user_id, None)
        STATE.pop(user_id, None)
    
        # 3) Start baseline (prefer new signature with seed; fallback to old)
        try:
            bl = handle_baseline(user_id, text, seed_concern_key=seed_key)  # preferred
        except TypeError:
            preface = f"We will keep *{human_label_for(seed_key)}* in mind.\n\n" if seed_key else ""
            hb = handle_baseline(user_id, text) or ""
            if isinstance(hb, dict):
                hb = hb.get("reply", "")
            bl = preface + hb
    
        if bl is not None:
            LAST_SEEN[user_id] = now
            # Normalize to the router’s shape
            return bl if isinstance(bl, dict) else {"reply": bl}

    # --- Lifestyle area intent: ask which pillar they want -------------------
    if any(p in lower for p in [
        "lifestyle area",
        "choose lifestyle area",
        "pick a lifestyle area",
        "pick an area",
        "choose an area",
        "lifestyle focus",
        "lifestyle",
    ]):
        set_state(user_id, **{"await": "lifestyle_pillar"})
    
        pillar = map_intent_to_pillar(text)
        if pillar:
            # we detected the pillar → jump straight to the clarifier
            set_state(user_id, **{"await": "pillar_detail", "pillar": pillar})
            LAST_SEEN[user_id] = now
            return {"reply": pillar_detail_prompt(pillar)}
        else:
            # couldn’t detect → show the menu prompt (so the user can pick one)
            LAST_SEEN[user_id] = now
            return {"reply": (
                "Which *lifestyle area* would you like to focus on?\n"
                "• Environment & Structure\n"
                "• Nutrition & Gut Health\n"
                "• Sleep\n"
                "• Exercise & Movement\n"
                "• Stress Management\n"
                "• Thought Patterns\n"
                "• Emotional Regulation\n"
                "• Social Connection\n\n"
                "Type the area (e.g., *sleep*)."
            )}
            
    # --- Handle the user's pillar choice (after we asked for a lifestyle area)
    if get_state(user_id).get("await") == "lifestyle_pillar":
        # allow quick jump to baseline at any time
        if "baseline" in lower:
            set_state(user_id, **{"await": None})
            LAST_SEEN[user_id] = now
            bl = handle_baseline(user_id, text)
            if bl is not None:
                return bl

        # try your existing mapper first (env/sleep/etc.)
        pillar = map_intent_to_pillar(text)

        # fallback normalisation for common variants
        if not pillar:
            pillar_map = {
                # environment cluster
                "environment": "environment", "structure": "environment", "routine": "environment",
                "organize": "environment", "organise": "environment",

                # nutrition cluster
                "nutrition": "nutrition", "gut": "nutrition", "food": "nutrition", "diet": "nutrition",
                "ibs": "nutrition", "bloating": "nutrition",

                # sleep
                "sleep": "sleep", "insomnia": "sleep",

                # movement
                "exercise": "movement", "movement": "movement", "walk": "movement", "steps": "movement",
                "workout": "movement",

                # stress
                "stress": "stress",

                # thoughts
                "thoughts": "thoughts", "mindset": "thoughts", "self talk": "thoughts", "self-talk": "thoughts",
                "motivation": "thoughts",

                # emotions
                "emotions": "emotions", "emotion": "emotions",

                # social
                "social": "social", "connection": "social", "friends": "social", "lonely": "social",
                "isolation": "social", "isolated": "social",
            }
            for k in pillar_map:
                if k in lower:
                    pillar = pillar_map[k]
                    break

        if not pillar:
            LAST_SEEN[user_id] = now
            return {"reply": (
                "I didn’t catch that pillar. Please type one of: environment, nutrition, sleep, "
                "movement, stress, thoughts, emotions, or social."
            )}

        # >>> NEW: jump to your tailored clarifier
        set_state(user_id, **{"await": "pillar_detail", "pillar": pillar})
        LAST_SEEN[user_id] = now
        return {"reply": pillar_detail_prompt(pillar)}

    # --- Follow-up after pillar choice: habit vs health concern (clarifier path)
    if get_state(user_id).get("await") == "pillar_detail":
        chosen = get_state(user_id).get("pillar") or map_intent_to_pillar(text) or "nutrition"
        human_label = PILLARS.get(chosen, {}).get("label", chosen.title())

        # NEW: set a SMARTS goal now (without looping back to menus)
        if any(k in lower for k in {"goal", "set goal", "smart goal", "set a goal"}):
            set_state(user_id, **{"await": "goal_text", "pillar": chosen})
            LAST_SEEN[user_id] = now
            return {"reply": (
                f"Let’s set a SMARTS goal for *{human_label}*.\n"
                "What’s one small, realistic action you’d like to take in the next week? "
                "For example: “lights out by 10:30pm on weeknights” or “add a palm of protein at lunch.”"
            )}

        # allow quick jump to baseline
        if "baseline" in lower:
            set_state(user_id, **{"await": None})
            LAST_SEEN[user_id] = now
            bl = handle_baseline(user_id, text)
            if bl is not None:
                return bl

        # NEW: if they ask for general tips/suggestions, give pillar advice now
        if any(k in lower for k in {"general tips", "tips", "advice", "suggestions"}):
            set_state(user_id, **{"await": None})
            LAST_SEEN[user_id] = now
            extra = (
                "\n\nEverything connects — improvements here support mood, stress, appetite and energy.\n"
                "Would you like to set a SMARTS goal to track progress? Type *baseline*. "
                "Or say *start* to begin the eity20 programme for this area."
            )
            return {"reply": compose_reply(chosen, f"general tips for {chosen}") + extra + tag}
        
        # If they named a health concern, branch to the concern/programme path
        concern_key = match_concern_key(text)
        if concern_key:
            LAST_CONCERN[user_id] = {"key": concern_key}
            set_state(user_id, **{"await": None})
            LAST_SEEN[user_id] = now
            prog_key = detect_program_key(text) or concern_key
            return {"reply": (
                f"Thank you — I heard *{human_label_for(concern_key)}*.\n"
                "Would you like to:\n"
                f"1) Start {program_pitch(prog_key)} (type: *start*)\n"
                "2) Do a 1-minute *baseline* to prioritise\n"
                "3) Or get *advice* for today?\n"
                f"{EITY20_TAGLINE}"
            )}
    
        # Otherwise treat their message as habit/context → focused advice
        set_state(user_id, **{"await": None})
        LAST_SEEN[user_id] = now
        connection = (
            "\n\nEverything links together — gains here can improve your mood, stress and overall health.\n"
            "Want a SMARTS goal to monitor progress? Type *baseline*. "
            "You can also *start* the eity20 programme for this area."
        )
        return {"reply": compose_reply(chosen, text) + connection + tag}

        # Optional: mid-conversation broad advice request → advice opening
        if is_advice_intent(text):
            LAST_SEEN[user_id] = now
            return {"reply": advice_opening_message()}

    # --- Capture the user's goal text and save it -------------------------------
    if get_state(user_id).get("await") == "goal_text":
        goal_text = (text or "").strip()
        pillar = get_state(user_id).get("pillar", "nutrition")

        # Try tracker first if it exposes a setter; else store temporarily.
        try:
            # If tracker.set_goal exists, use it; otherwise the import will fail and we fall back.
            from tracker import set_goal as tracker_set_goal  # optional
            tracker_set_goal(user_id=user_id, text=goal_text, pillar_key=pillar, cadence="most days")
            saved_via_tracker = True
        except Exception:
            saved_via_tracker = False

        if not saved_via_tracker:
            # Fallback: keep it in-memory so conversation can continue.
            PENDING_GOALS[user_id] = {"text": goal_text, "pillar": pillar, "cadence": "most days"}

        clear_state(user_id)
        LAST_SEEN[user_id] = now
        return {"reply": (
            f"Goal saved: “{goal_text}” (Pillar: {pillar.title()}, cadence: most days).\n"
            "Say **done** whenever you complete it; say **progress** to see your last 14 days.\n\n"
            "Want a couple of helpful tips for this area? Say **general tips**."
        )}

    # 3) Human menu triggers for open-ended requests
    MENU_TRIGGERS = {
        "help", "support", "change my lifestyle", "change my life",
        "improve my lifestyle", "get healthier", "where do i start"
    }
    if any(phrase in lower for phrase in MENU_TRIGGERS):
        LAST_SEEN[user_id] = now
        return {"reply": (
            "I completely understand. We’ll use eity20’s 8 pillars to prevent ill health and for lasting health & wellbeing.\n\n"
            "How would you like to begin?\n"
            "• Type a *health concern* (e.g., cholesterol, depression, IBS)\n"
            "• Type a *lifestyle area* (e.g., sleep, nutrition, movement, stress)\n"
            "• Type *advice* for general tips\n"
            "• Type *baseline* for a 1-minute assessment\n\n"
            "Aim for 80% consistency, 20% flexibility — 100% human."
        )}

    # 4) Concern-first (if the message clearly contains a priority concern)
    stack = detect_priority_stack(text)
    if stack:
        key = match_concern_key(text) or "blood sugar"
        reply = make_concern_intro_reply(key, stack, user_text=text)
        LAST_CONCERN[user_id] = {"key": key, "stack": stack}
        LAST_SEEN[user_id] = now
        return {"reply": reply + tag}

    # 5) Pillar advice (direct keyword routing)
    if any(k in lower for k in ["environment", "structure", "routine", "organise", "organize"]):
        LAST_SEEN[user_id] = now
        return {"reply": compose_reply("environment", text)}
    if any(k in lower for k in ["nutrition", "gut", "food", "diet", "ibs", "bloating"]):
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

    # 6) Intent/concern mapper → pillar → playbook
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

    # 7) OpenAI fallback (short, warm, actionable, 80/20 tone)
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

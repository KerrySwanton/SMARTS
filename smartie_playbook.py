# smartie_playbook.py

EITY20_TAGLINE = "Aim for 80% consistency, 20% flexibility — 100% human."

# -------------------------------------------------
# Nutrition library (80% foundation / 20% flexibility)
# -------------------------------------------------

def _norm(s: str) -> str:  # simple normaliser for keyword matching
    return (s or "").lower()

NUTRITION_80 = {
    "starchy_carbohydrates": {
        "whole_grains": [
            "brown rice","wild rice","corn","whole oats","quinoa","barley",
            "rye","amaranth","buckwheat","spelt","sorghum","bulgur wheat","freekeh"
        ],
        "starchy_foods": [
            "bread","crackers","rice cakes","oat cakes","breakfast cereal (Weetabix, Bran Flakes, All Bran)",
            "popcorn","couscous","pasta","noodles"
        ],
        "fruit": [
            "bananas","apples","kiwifruit","berries","mango","citrus fruits",
            "pineapple","plums","raisins","dates"
        ],
        "vegetables": [
            "parsnips","carrots","white potato","sweet potato","corn","peas","squash"
        ],
        "nutritional_benefits": [
            "high fibre (gut health)","B vitamins (e.g. thiamine for energy & nerves)",
            "folate (blood cells & nervous system)","magnesium (reduces fatigue)",
            "copper (immune function)","antioxidants (vit C, E, flavonoids, polyphenols)"
        ],
        "health_benefits": [
            "steady energy & blood sugar","improves gut health",
            "supports mood, concentration, cognition; reduces brain fog",
            "satiating; supports healthy cholesterol & heart health; lowers risk of T2D & bowel cancer"
        ],
    },

    "protein": {
        "lean_meat": ["chicken","turkey","beef (moderation)","lamb (moderation)","venison","pork (moderation)","veal","goat"],
        "organ_meat": ["liver","kidney","heart"],
        "oily_fish": ["salmon","trout","mackerel","sardines","whitebait"],
        "dairy": ["milk","yoghurt","cheese","cream cheese"],
        "dairy_alternatives": ["soya drinks","soya yoghurts","oat milk","nut milks","rice milk"],
        "legumes": [
            "beans (kidney, soybeans, chickpeas, butter, cannellini)",
            "lentils (puy, green, brown, red, black)",
            "peas (chickpeas, split peas, sweet peas, shelling peas)"
        ],
        "nutritional_benefits": [
            "high-quality protein","fibre (legumes)","iron, zinc, selenium, calcium",
            "B vitamins (B12, B6, B9, B2)","vitamins A, D",
            "omega-3 fatty acids","taurine, creatine, carnitine, carnosine",
            "tryptophan, tyrosine"
        ],
        "health_benefits": [
            "muscle growth & repair; stronger tendons","reduces sarcopenia & bone loss",
            "better sleep patterns","satiating (supports weight management)",
            "tryptophan → serotonin/melatonin (mood & sleep)","tyrosine → dopamine & adrenaline (emotion & stress regulation; thyroid support)"
        ],
    },

    "healthy_unsaturated_fat": {
        "oily_fish": ["salmon","mackerel","sardines","anchovies","kippers","pilchards","trout","herring"],
        "seeds": ["flax","chia","sesame","sunflower"],
        "nuts": ["almonds","brazil nuts","walnuts","hazelnuts"],
        "plant_oils": ["olive oil","rapeseed oil","flaxseed oil","soybean oil"],
        "fortified_omega3": ["eggs","yoghurt","milk","soy beverages","bread","butter spreads"],
        "fruit_veg_fats": ["avocados","olives","coconut"],
        "nutritional_benefits": [
            "fibre (seeds)","vitamin B12 & D (fish)","omega-3 & omega-6 fatty acids",
            "MUFAs (olive oil, avocado)","PUFAs (walnuts, fish)","improves absorption of vitamins A, D, E, K"
        ],
        "health_benefits": [
            "supports heart health (BP, clotting)","lower dementia risk (esp. Alzheimer’s)",
            "improves cognition & working memory","benefits ADHD symptoms (attention, impulsivity)",
            "regulates mood (depression)","eye health (reduced AMD risk)",
            "reduces inflammation (e.g., RA, joint health)","may lower breast/colon cancer risk"
        ],
    },

    "fruit_veg_target": {
        "guidance": ["aim ≥5 portions/day; rich in antioxidants, nutrients & fibre for brain and body"]
    },

    "gut_brain_support": {
        "examples": [
            "antioxidants","omega-3 fatty acids","probiotics & prebiotics",
            "high-fibre foods","fermented foods (sauerkraut, kimchi, Greek yoghurt, kefir)"
        ]
    },

    "fluids": {
        "guidance": ["drink 6–8 glasses (≈2L) water daily; supports cognition, attention, emotions, energy"]
    },
}

NUTRITION_20 = {
    "unhealthy_saturated_fat": {
        "snacks": ["peanuts (salted/roasted)","vegetable crisps","crisps","milk/white chocolate","cheese straws"],
        "takeaway": ["pizza","curry","fish & chips","burgers","Chinese"],
        "processed": ["processed meats (ham, bacon, salami, sausage, pâté, tinned)","ready meals","powdered soup",
                      "packaged cakes, pastries, biscuits, puddings"],
    },
    "sugar_and_alcohol": {
        "alcohol": [
            "wine (red/white/rosé)","sparkling (Prosecco, Champagne)","beer/lager/ale/stout/cider",
            "spirits (gin, whisky, rum, vodka)","alcopops (e.g., Smirnoff Ice, Bacardi Breezer, WKD)"
        ],
        "processed_drinks": ["fizzy drinks (cola, lemonade, Fanta)","energy drinks (Monster, Red Bull)"],
        "processed_foods": [
            "confectionery (chocolate, sweets)","ready meals","powdered soups","breakfast cereals & bars",
            "packaged cakes, pastries, biscuits, puddings","canned fruit in syrup","ice cream","bread/rolls (sweetened)"
        ],
    },
    "salt_processed": {
        "salty_snacks": ["crisps","salted nuts","biscuits","popcorn"],
        "cheese": ["halloumi","blue cheese"],
        "takeaway": ["pizza","curry","Chinese"],
        "processed": ["ready meals","processed meat (sausages, bacon, ham, pâté, chorizo, salami)",
                      "retail sauces (ketchup, soy sauce, mayonnaise, pickles, pasta sauces)"],
    },
}

# quick keyword detector for "food lists" requests
_FOOD_KEYS = {"food","foods","eat","eating","protein","carb","carbs","fat","fats","snack","snacks","examples","list","what to eat"}

def wants_food_list(user_line: str) -> bool:
    t = _norm(user_line)
    return any(k in t for k in _FOOD_KEYS)

def _fmt(items: list[str], max_n=8) -> str:
    if not items:
        return ""
    cut = items[:max_n]
    more = "…" if len(items) > max_n else ""
    return ", ".join(cut) + more

def nutrition_foods_answer(user_line: str) -> str:
    """
    Return an 80/20 foods overview or a focused category list based on the user query.
    Keeps output compact and scannable, with prompts to ask for more.
    """
    t = _norm(user_line)

    # If user hints at "20%" (treats/sugar/takeaway/alcohol)
    if any(k in t for k in ["treat","20","twenty","alcohol","sugar","sweet","takeaway","crisps","chocolate","salt"]):
        lines = ["**20% Flexibility — examples (use sparingly):**"]
        u = NUTRITION_20
        lines += [
            f"- Saturated fat (snacks): {_fmt(u['unhealthy_saturated_fat']['snacks'])}",
            f"- Saturated fat (takeaway): {_fmt(u['unhealthy_saturated_fat']['takeaway'])}",
            f"- Saturated fat (processed): {_fmt(u['unhealthy_saturated_fat']['processed'])}",
            f"- Sugar & alcohol (alcohol): {_fmt(u['sugar_and_alcohol']['alcohol'])}",
            f"- Sugar & alcohol (drinks): {_fmt(u['sugar_and_alcohol']['processed_drinks'])}",
            f"- Sugar & alcohol (foods): {_fmt(u['sugar_and_alcohol']['processed_foods'])}",
            f"- Salt/processed (snacks): {_fmt(u['salt_processed']['salty_snacks'])}",
            f"- Salt/processed (processed): {_fmt(u['salt_processed']['processed'])}",
        ]
        lines.append(EITY20_TAGLINE)
        return "\n".join(lines)

    # 80% defaults or specific categories
    eighty = NUTRITION_80
    lines = ["**80% Foundation — everyday foods:**"]

    if any(k in t for k in ["protein","meat","fish","dairy","legume","beans","lentil"]):
        p = eighty["protein"]
        lines += [
            f"- Lean meat: {_fmt(p['lean_meat'])}",
            f"- Oily fish: {_fmt(p['oily_fish'])}",
            f"- Dairy/alt: {_fmt(p['dairy'])}; {_fmt(p['dairy_alternatives'])}",
            f"- Legumes: {_fmt(p['legumes'])}",
            f"- Benefits: {_fmt(p['health_benefits'], max_n=4)}",
        ]
    elif any(k in t for k in ["carb","carbs","starch","grain","oats","rice","pasta","bread","cereal","noodles"]):
        s = eighty["starchy_carbohydrates"]
        lines += [
            f"- Whole grains: {_fmt(s['whole_grains'])}",
            f"- Starchy foods: {_fmt(s['starchy_foods'])}",
            f"- Fruit: {_fmt(s['fruit'])}",
            f"- Vegetables: {_fmt(s['vegetables'])}",
            f"- Benefits: {_fmt(s['health_benefits'], max_n=4)}",
        ]
    elif any(k in t for k in ["fat","fats","omega","nuts","seeds","oil","olive","avocado"]):
        f = eighty["healthy_unsaturated_fat"]
        lines += [
            f"- Oily fish: {_fmt(f['oily_fish'])}",
            f"- Nuts & seeds: {_fmt(f['nuts'])}; {_fmt(f['seeds'])}",
            f"- Plant oils: {_fmt(f['plant_oils'])}",
            f"- Fruit/veg fats: {_fmt(f['fruit_veg_fats'])}",
            f"- Benefits: {_fmt(f['health_benefits'], max_n=4)}",
        ]
    elif any(k in t for k in ["gut","microbiome","fermented","fibre","fiber","kefir","yoghurt","yogurt","kimchi"]):
        g = eighty["gut_brain_support"]
        lines += [
            f"- Examples: {_fmt(g['examples'])}",
            "Tip: add one fermented food 3x/week.",
        ]
    elif any(k in t for k in ["fruit","veg","vegetable","5-a-day","5 a day"]):
        fv = eighty["fruit_veg_target"]
        lines += [
            f"- Guidance: {_fmt(fv['guidance'])}",
            "Tip: add 1 portion at lunch today.",
        ]
    elif any(k in t for k in ["drink","water","fluid","hydrate","hydration"]):
        fl = eighty["fluids"]
        lines += [
            f"- Guidance: {_fmt(fl['guidance'])}",
            "Tip: carry a bottle; aim for 6–8 glasses.",
        ]
    else:
        # General overview
        s = eighty["starchy_carbohydrates"]; p = eighty["protein"]; f = eighty["healthy_unsaturated_fat"]
        lines += [
            f"- Carbs (grains/veg/fruit): {_fmt(s['whole_grains'])}",
            f"- Protein (meat/fish/dairy/legumes): {_fmt(p['legumes'])}",
            f"- Healthy fats (oils/nuts/seeds/fish): {_fmt(f['plant_oils'])}",
            "Ask for details: try 'protein ideas', 'healthy fats', 'gut-friendly foods', or 'show 20%'.",
        ]

    lines.append(EITY20_TAGLINE)
    return "\n".join(lines)

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
    Smartie's advice-first composer.
    - If the user explicitly asks for advice/tips, answer with 2 concrete steps
      and (optionally) offer a SMARTS-shaped goal.
    - Otherwise, give a short warm line plus one generic tiny-step nudge.
    """
    pk = pillar_key
    p = PILLARS.get(pk)
    if not p:
        return "Thank you for asking — what exactly would you like to know?"

    # NEW: if nutrition + user asks for foods/examples → return foods answer directly
    if pk == "nutrition" and wants_food_list(user_line):
        return nutrition_foods_answer(user_line)

    label = p["label"]
    text = (user_line or "").lower()

    # --- Detect explicit "ask for advice" intent ---
    advice_markers = [
        "advice", "tip", "tips", "help", "how do i", "how to", "what should",
        "ideas", "suggest", "suggestion", "recommend", "recommendation", "plan",
        "where to start", "what can i do", "can you help"
    ]
    is_advice = any(m in text for m in advice_markers) or text.endswith("?")

    # --- Quick routing to a specific suggestion index (if a keyword appears) ---
    specific_map = {
        "nutrition": {
            "meal": 0, "timing": 0, "breakfast": 0, "regular": 0,
            "protein": 1, "snack": 1, "veg": 1, "fruit": 1, "plants": 1,
            "gut": 2, "bloat": 2, "ibs": 2, "fibre": 2, "fiber": 2
        },
        "sleep": {
            "wind": 0, "bed": 0, "screen": 0, "caffeine": 0,
            "wake": 1, "waking": 1, "night": 1,
            "morning": 2, "light": 2, "sun": 2
        },
        "exercise": {
            "walk": 0, "steps": 0,
            "strength": 1, "weights": 1,
            "stretch": 2, "mobility": 2
        },
        "stress": {
            "breathe": 0, "breathing": 0,
            "worry": 1, "ruminate": 1, "rumination": 1,
            "pause": 2, "decompress": 2
        },
        "thoughts": {
            "self-talk": 0, "talk": 0, "kind": 0,
            "perfection": 1, "perfect": 1,
            "reframe": 2, "reframing": 2
        },
        "emotions": {
            "soothe": 0, "soothing": 0,
            "urge": 1, "craving": 1, "binge": 1, "comfort": 1,
            "journal": 2, "journaling": 2
        },
        "social": {
            "ask": 0, "help": 0, "support": 0,
            "friend": 1, "connect": 1, "connection": 1,
            "boundary": 2
        },
        "environment": {
            "morning": 0, "start": 0,
            "evening": 1, "reset": 1,
            "cue": 2, "cues": 2, "visual": 2
        },
    }

    if is_advice:
        # 1) Try to detect a specific subtopic to pick a step directly
        chosen_idx = None
        for kw, idx in specific_map.get(pk, {}).items():
            if kw in text:
                chosen_idx = idx
                break

        # 2) Build the two concrete steps (rotate or fallback to generic list)
        suggestions = p.get("suggestions", [])
        if not suggestions:
            suggestions = [
                "Pick one 5-minute action you can repeat this week.",
                "Keep it realistic and time-anchored."
            ]

        s1 = suggestions[chosen_idx or 0]
        s2 = suggestions[((chosen_idx or 0) + 1) % len(suggestions)]

        # 3) Offer a goal (optional)
        offer = propose_smarts_goal(pk, user_line=user_line)
        goal_line = f"\n{offer['offer']}" if offer.get("offer") else ""

        return "\n".join([
            "Yes — of course. Here are two tiny actions you can try:",
            f"• {s1}",
            f"• {s2}",
            EITY20_TAGLINE,
            f"(Pillar: {label})",
        ]) + goal_line

    else:
        # Default: not explicitly asking for advice → warm nudge + tiny step
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

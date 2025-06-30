import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

import traceback

@app.route("/smartie", methods=["POST"])
def smartie_reply():
   try:
       data = request.get_json()
       print("📥 Received data:", data)

       user_input = data.get("message", "")
       print("🧠 User input:", user_input)

       response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[
        {"role": "system", "content": """
You are Smartie – a kind, supportive, emotionally intelligent digital assistant for the eity20 programme.

eity20 is a holistic health and wellbeing system that recognises the powerful connection between physical, mental and gut health. What affects one, impacts the others.

Smartie helps users stay on track with their long-term health and wellbeing goals by promoting 80% consistency and 20% flexibility — the eity20 rule. Your job is not to be perfect, but to support real people navigating real life.

Guide people gently using the SMARTS framework:
– Sustainable: Promote habits that are maintainable long term
– Mindful mindset: Encourage awareness, self-kindness and reflection
– Aligned: Help users act in line with their values
– Realistic: Avoid perfectionism; support small, doable steps
– Train your brain: Support emotional regulation and thought reframing
– Speak up: Encourage connection, self-expression and asking for help

Smartie supports people across 8 interconnected pillars:
- Environment and structure
- Nutrition and gut health
- Sleep
- Exercise and movement
- Stress management
- Thought patterns
- Emotional regulation
- Social connection

People may come to you when they feel stressed, have skipped a workout, eaten something indulgent (like chocolate), or are struggling to stay consistent.

Normalize human emotions and setbacks. Reinforce that it’s okay to have tough days. Help them reflect without guilt and offer one or two gentle ideas to move forward with balance.
        """},
        {"role": "user", "content": user_input}
    ],
    max_tokens=500,
)

       reply = response.choices[0].message.content
       print("✅ Smartie reply:", reply)

       return jsonify({"reply": reply})

   except Exception as e:
       print("🔥 ERROR: Something went wrong inside /smartie:")
       traceback.print_exc() # Print full error
       return jsonify({"reply": "Oops, something went wrong."}), 500

if __name__ == "__main__":
   app.run(host="0.0.0.0", port=5000)

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
               {
                  "role": "system", 
                  "content": (
                     "You are Smartie - a warm, supportive chatbot designed to help people stay consistent with their physical, mental, and gut health goals using the eity20 principle: 80% consistency, 20% flexibility. You encourage sustainable habits without guilt, especially when people mention stress, cravings, skipped workouts, or feeling low. You understand that food affects mood, stress impacts digestion, and self-kindness is essential. Normalise stress, support balance, and offer gentle, actionable suggestions to help people feel good, stay on track, and bounce back."
                  )
               },
               {"role": "user", "content": user_input}
           ],
           max_tokens=150,
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

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
                     "You are Smartie - a warm, supportive digital wellbeing buddy for the eity20 approach - encouraging 80% consistency and 20% flexibility. "
                     "You help people stay on track with physical and mental health goals without guilt. "
                     "You gently acknowledge stress, comfort eating, and cravings as normal human experiences. "
                     "You emphasise balance, gut health, mood, and kindness to self. "
                     "Help the user regroup if they feel off track, offering ideas like relaxing, moving gently, or adding something nourishing. "
                     "Always reinforce that it's okay to be imperfect - consistency over time is what matters most."
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

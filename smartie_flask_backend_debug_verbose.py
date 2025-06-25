from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os

app = Flask(__name__)
CORS(app)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

@app.route("/smartie", methods=["POST"])
def smartie_reply():
    try:
        if not request.is_json:
            print("❌ Request is not JSON")
            return jsonify ({"reply": "Request must be in JSON format"}), 400
               
        data = request.get_json()
        print("📦 Request JSON:", data)

        user_input = data.get("message", "")
        print("🗣️ User input:", user_input)

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are Smartie, a warm, supportive health and wellbeing companion."},
                {"role": "user", "content": user_input}
            ],
            max_tokens=150,
        )

        reply = response.choices[0].message.content
        print("💬 OpenAI reply:", reply)

        return jsonify({"reply": reply})

    except Exception as e:
        print("❌ Error:", str(e))
        return jsonify({"reply": "Oops, something went wrong."}), 500

if __name__ == "__main__":
    print("🔐 OPENAI_API_KEY exists:", bool(os.environ.get("OPENAI_API_KEY")))
    app.run(host="0.0.0.0", port=5000)

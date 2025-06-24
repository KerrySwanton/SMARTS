
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import os

# Load OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY", "your_openai_api_key_here")

app = Flask(__name__)
CORS(app)  # Enable CORS

@app.route("/smartie", methods=["POST"])
def smartie_reply():
    data = request.json
    user_input = data.get("message", "")

    prompt = f"You are Smartie, a compassionate AI coach using the SMARTS framework. Help the user using principles like 80/20 thinking, habit formation, and emotional support. The user says: '{user_input}'"

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a kind, motivational AI coach named Smartie, trained in SMARTS principles."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=150
    )

    reply = response['choices'][0]['message']['content'].strip()
    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

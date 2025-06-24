
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

# Set up Flask app
app = Flask(__name__)
CORS(app)

# Set up OpenAI client
print("OPENAI_API_KEY exists:", bool(os.environ.get("OPENAI_API_KEY")))

@app.route("/smartie", methods=["POST"])
def smartie_reply():
    data = request.get_json()
    user_input = data.get("message", "")

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are Smartie, a warm, supportive health and wellbeing companion built on the eity20 framework. Respond with encouragement, insight, and helpful suggestions."},
                {"role": "user", "content": user_input}
            ],
            max_tokens=150,
            temperature=0.7
        )
        print("OpenAI raw response:", response)
        reply = response.choices[0].message.content
        return jsonify({"reply": reply})

    except Exception as e:
        print("Error from OpenAI:", e)
        return jsonify({"reply": "Oops, something went wrong on my end. Try again later."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

print ("👋 Smartie backend file is running")

from flask import Flask, request, jsonify
print ("✅ Flask imported")

from flask_cors import CORS
print ("✅ CORS imported")

from openai import OpenAI
print ("✅ OpenAI imported")

app = Flask(__name__)
CORS(app)

print ("✅ Flask app and CORS set up")

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
print ("🔑 OpenAI client initialized")

@app.route("/smartie", methods=["POST"])
def smartie_reply():
    try:
        print("✅ Smartie route hit - about to parse request")

        # Add this to help diagnose
        print ("🛠 Request object:", request)
               
        data = request.get_json()
        print("📦 Request JSON:", data)

        user_input = data.get("message", "")
        print("🗣️ User input:", user_input)

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are Smartie, a warm, supportive health and wellbeing companion built on the eity20 framework. Respond with encouragement, insight, and helpful suggestions."},
                {"role": "user", "content": user_input}
            ],
            max_tokens=150,
            temperature=0.7
        )

        print("🤖 OpenAI raw response:", response)

        reply = response.choices[0].message.content
        print("💬 Reply extracted:", reply)

        return jsonify({"reply": reply})

    except Exception as e:
        print("❌ Error from OpenAI:", e)
        return jsonify({"reply": "Oops, something went wrong on my end. Try again later."}), 500

if __name__ == "__main__":
    print("🔐 OPENAI_API_KEY exists:", bool(os.environ.get("OPENAI_API_KEY")))
    app.run(host="0.0.0.0", port=5000)

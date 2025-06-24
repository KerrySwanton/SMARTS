
# Smartie Backend

A Flask app that serves a supportive AI chatbot using the SMARTS framework.

## 📦 Includes
- smartie_flask_backend.py
- requirements.txt

## 🚀 How to Deploy on Render

1. Upload this folder to a new GitHub repo
2. Go to [https://render.com](https://render.com)
3. Click "New Web Service"
4. Connect your repo

### Settings
- Build Command: `pip install -r requirements.txt`
- Start Command: `python smartie_flask_backend_debug.py`
- Environment variable:
  - Key: `OPENAI_API_KEY`
  - Value: *your real OpenAI API key*

### Test Your Endpoint
POST to:
```
https://your-app.onrender.com/smartie
```
Send:
```json
{ "message": "I had a tough day" }
```

import os
import requests
from flask import Flask

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running live!"

def send_startup_message():
    if not TOKEN or not CHAT_ID:
        print("Token or Chat ID is missing!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": "🚀 تم تشغيل البوت بنجاح على Render وهو متصل الآن!"
    }
    try:
        response = requests.post(url, json=payload)
        print("Telegram response:", response.text)
    except Exception as e:
        print("Error sending message:", e)

if __name__ == "__main__":
    send_startup_message()
    app.run(host="0.0.0.0", port=PORT)

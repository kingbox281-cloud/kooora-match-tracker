import os
import time
import requests
from threading import Thread
from flask import Flask

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running live!"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

def send_telegram_message(text):
    if not TOKEN or not CHAT_ID:
        print("Telegram Token or Chat ID is missing!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }
    try:
        response = requests.post(url, json=payload)
        print("Telegram response:", response.text)
    except Exception as e:
        print("Error sending message:", e)

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    try:
        response = requests.get(url, params=params)
        return response.json()
    except Exception as e:
        print("Error getting updates:", e)
        return None

def bot_loop():
    print("Bot is running and listening for commands...")
    send_telegram_message("🤖 Bot is online and ready for testing! Send 'test' to check.")
    
    offset = None
    while True:
        updates = get_updates(offset)
        if updates and "result" in updates:
            for update in updates["result"]:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text", "").strip().lower()
                
                if text in ["test", "/test"]:
                    send_telegram_message("✅ [TEST MODE] تم استلام رسالة الاختبار بنجاح! البوت يعمل بشكل ممتاز.")
        
        time.sleep(1)

if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.start()
    bot_loop()

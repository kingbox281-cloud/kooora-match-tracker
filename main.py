import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token or chat ID is missing!")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        print(f"Telegram response: {response.text}")
    except Exception as e:
        print(f"Error sending message: {e}")

def background_monitor():
    # إرسال رسالة فورية للتأكد من نجاح الاتصال وتفعيل البوت
    send_telegram_message("🚀 *تم تفعيل نظام رصد الفجوات وتليجرام متصل بنجاح!*")
    
    while True:
        try:
            print("جاري فحص المباريات لكشف الفجوات...")
            
            # نموذج تجريبي لفحص الفجوة بين كووورة والمنصات
            matches_to_check = [
                {
                    "name": "Real Madrid vs Barcelona",
                    "kooora_status": "Ended",
                    "platforms": [
                        {"name": "Tipwin", "status": "Not Started"}
                    ]
                }
            ]
            
            for match in matches_to_check:
                if match["kooora_status"] == "Ended":
                    for platform in match["platforms"]:
                        if platform["status"] != "Ended":
                            alert_message = (
                                f"🚨 *تنبيه فجوة تأخير عاجل!*\n\n"
                                f"⚽ *المباراة:* {match['name']}\n"
                                f"🛑 *الحالة في المصدر الرسمي (كووورة):* انتهت تماماً\n"
                                f"⏳ *الحالة في المنصة:* لا تزال معروضة أو لم تبدأ بعد في **{platform['name']}**\n\n"
                                f"⚡ *سارع بالتحقق واغتنام الفرصة!*"
                            )
                            send_telegram_message(alert_message)
            
            time.sleep(60)
        except Exception as e:
            print(f"خطأ في حلقة المراقبة: {e}")
            time.sleep(30)

@app.route('/')
def home():
    return "Delay Betting Bot is running!"

if __name__ == '__main__':
    t = threading.Thread(target=background_monitor, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

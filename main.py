import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

# قراءة المتغيرات السرية من إعدادات Render
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

def check_kooora_delay_betting():
    """
    دالة فحص ومقارنة حالة المباريات بين كووورة ومنصات المراهنات
    """
    # --- نموذج بيانات للمباريات الحية قيد المراقبة ---
    # (لاحقاً سنربط هذه القائمة ببيانات حية يتم جلبها تلقائياً)
    matches_to_check = [
        {
            "name": "Team A vs Team B",
            "kooora_status": "Ended",  # انتهت تماماً في كووورة
            "platforms": [
                {"name": "Tipwin", "status": "Not Started / Active"},
                {"name": "Sportwetten", "status": "Active"},
                {"name": "Merkur Bets", "status": "Live"}
            ]
        }
    ]
    
    for match in matches_to_check:
        match_name = match["name"]
        kooora_status = match["kooora_status"]
        
        for platform in match["platforms"]:
            platform_name = platform["name"]
            platform_status = platform["status"]
            
            # شرط اكتشاف الفجوة: المباراة انتهت في كووورة ولكنها ما زالت نشطة أو لم تبدأ بشكل صحيح في المنصة
            if kooora_status == "Ended" and platform_status != "Ended":
                
                # صياغة التنبيه الفوري بالشكل المطلوب
                alert_message = (
                    f"🚨 *تنبيه فجوة تأخير عاجل!*\n\n"
                    f"⚽ *المباراة:* {match_name}\n"
                    f"🛑 *الحالة في المصدر الرسمي (كووورة):* انتهت تماماً\n"
                    f"⏳ *الحالة في المنصة:* لا تزال معروضة أو لم تبدأ بعد في **{platform_name}**\n\n"
                    f"⚡ *سارع بالتحقق واغتنام الفرصة!*"
                )
                
                # إرسال التنبيه فوراً إلى تيليجرام
                send_telegram_message(alert_message)

def background_monitor():
    send_telegram_message("🚀 *تم تفعيل نظام المراقبة الآلية لفجوات التأخير بنجاح!*")
    
    while True:
        try:
            print("جاري فحص المباريات لكشف الفجوات...")
            
            # تنفيذ دالة المقارنة والفحص
            check_kooora_delay_betting()
            
            # الفترة الزمنية بين كل عملية فحص وأخرى (مثلاً كل 60 ثانية)
            time.sleep(60)
            
        except Exception as e:
            print(f"حدث خطأ في حلقة المراقبة: {e}")
            time.sleep(30)

@app.route('/')
def home():
    return "Delay Betting Bot is active and monitoring!"

if __name__ == '__main__':
    # تشغيل نظام المراقبة في خيط (Thread) خلفي مستقل
    t = threading.Thread(target=background_monitor, daemon=True)
    t.start()
    
    # تشغيل سيرفر الفلاسك
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

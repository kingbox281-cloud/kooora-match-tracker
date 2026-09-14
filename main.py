import time
import requests

# ==================== إعدادات الإتصال ====================
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"

# رابط صفحة المباريات الأساسي للمراقبة
KOOORA_LIVE_URL = "https://www.kooora.com/?live=1"

# قائمة الـ 18 منصة التي يتم مراقبتها
LIST_OF_18_PLATFORMS = [
    "Tipico", "bet365", "Merkur Bets", "ODDSET", "bwin", 
    "Interwetten", "Bet-at-home", "NEO.BET", "Betway", "Winamax",
    "Sportingbet", "TOTO", "Betano", "Pox Gewinnspiel", "HappyBet",
    "Cashpoint", "Boylesports", "Vbet"
]

# ==================== وظائف البوت ====================

def send_telegram_alert(country, league_name, match_name, match_score, kooora_status, delayed_platforms):
    """إرسال تنبيه منظم ومرتب إلى تليجرام مع دمج النتيجة بجانب الفريقين"""
    
    delayed_list_str = ""
    for p in delayed_platforms:
        delayed_list_str += f"  🟢 `{p}`\n"
        
    closed_count = len(LIST_OF_18_PLATFORMS) - len(delayed_platforms)

    message = (
        "🚨 *رصد فجوة مراهنات (Arbitrage Gap Detected!)* 🚨\n\n"
        f"🌍 *الدولة:* {country}\n"
        f"🏆 *البطولة / الدوري:* {league_name}\n"
        f"⚽ *المباراة:* {match_name} ({match_score})\n"
        f"⏱️ *حالة المصدر (كووورة):* {kooora_status} 🛑\n\n"
        "📊 *حالة المنصات الـ 18:*\n"
        "• *المتأخرة (تسمح بالرهان / Pre-match):*\n"
        f"{delayed_list_str}\n"
        "• *المغلقة (سليمة):*\n"
        f"  🔴 {closed_count} منصات أُغلقت في الوقت المناسب\n\n"
        "⚡ _يرجى التحقق والتوجه للمنصة فوراً!_"
    )
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ خطأ في إرسال التنبيه عبر تيليجرام: {e}")

def fetch_kooora_matches_today():
    """
    دالة جلب وتجميع المباريات الحقيقية من كووورة والمنصات.
    يجب أن تعيد هذه الدالة قائمة من القواميس (List of Dicts) بالهيكل التالي الحقيقي:
    [
       {
           "country": "اسم الدولة",
           "league": "اسم البطولة/الدوري",
           "name": "اسم الفريقين (مثلاً: بايرن ميونخ vs دورتموند)",
           "score": "النتيجة النهائية (مثلاً: 3 - 1)",
           "status": "حالة المباراة الحقيقية من كووورة (مثل FT)",
           "platforms_status": {
               "Merkur Bets": "Pre-match أو Closed",
               "Tipico": "Pre-match أو Closed",
               ... وباقي المنصات الـ 18
           }
       }
    ]
    """
    matches_list = []
    
    try:
        # --- [ضع كود السحب الحقيقي الخاص بك هنا لجلب المباريات والنتائج وحالة المنصات] ---
        pass
        
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب البيانات من الموقع: {e}")
        
    return matches_list

def run_arbitrage_bot():
    """حلقة العمل الرئيسية التي تعمل بلا توقف 24/7 لمراقبة السوق"""
    print("🤖 بدأ تشغيل بوت مراقبة فجوات كووورة بنجاح...")
    
    while True:
        try:
            print("🔄 جاري فحص مباريات اليوم وتحديث الحالة...")
            
            # 1. جلب قائمة مباريات اليوم الحقيقية
            matches = fetch_kooora_matches_today()
            
            for match in matches:
                country = match.get("country", "غير محدد")
                league = match.get("league", "بطولة غير محددة")
                match_name = match.get("name")
                match_score = match.get("score", "0 - 0")
                status = match.get("status")
                platforms_data = match.get("platforms_status", {})
                
                # 2. التحقق مما إذا كانت المباراة قد انتهت فعلاً على كووورة
                if status in ["FT", "انتهت", "Ended"]:
                    delayed_platforms = []
                    
                    # 3. الفحص على المنصات الـ 18 الحقيقية
                    for platform in LIST_OF_18_PLATFORMS:
                        p_status = platforms_data.get(platform, "Closed")
                        if p_status == "Pre-match":
                            delayed_platforms.append(platform)
                    
                    # 4. إذا وجدت منصات متأخرة حقيقية، أرسل تنبيه فوري
                    if len(delayed_platforms) > 0:
                        print(f"🚨 تم رصد ثغرة للمباراة: {match_name} ({match_score}) - {league}")
                        send_telegram_alert(country, league, match_name, match_score, status, delayed_platforms)
                
            # الانتظار لدقيقة واحدة قبل الدورة التالية لتجنب الحظر
            time.sleep(60)
            
        except Exception as e:
            print(f"⚠️ حدث خطأ في الحلقة الرئيسية: {e}")
            time.sleep(30)

# نقطة بداية التشغيل
if __name__ == "__main__":
    run_arbitrage_bot()


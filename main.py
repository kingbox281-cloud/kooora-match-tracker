def check_kooora_matches():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(KOOORA_URL, headers=headers, timeout=15)
        print(f"Kooora response status: {response.status_code}")
        
        current_time = datetime.now().strftime("%H:%M:%S")
        send_telegram_message(f"🔄 البوت قام بعملية فحص حديثة لموقع كووورة بنجاح في الساعة `{current_time}` وحالة الاتصال: `{response.status_code}`")
        
        if response.status_code != 200:
            return
        
        soup = BeautifulSoup(response.text, 'html.parser')
        current_league = "الدوري العام"
        current_country = "الدولي / محلي"
        
        # البحث في جدول المباريات بطريقة دقيقة تلتقط المباريات وحالاتها
        # موقع كووورة يضع المباريات غالباً داخل عناصر تحتوي على الفرق والحالة
        matches = soup.find_all('tr') or soup.find_all('div', class_='match')
        
        for match in matches:
            text = match.get_text(separator=" ", strip=True)
            
            # تحديث اسم البطولة إذا وجد في السطر
            if 'الدوري' in text or 'كأس' in text or 'بطولة' in text or 'دوري' in text:
                parts = [p.strip() for p in text.split('-') if len(p.strip()) > 3]
                if parts:
                    current_league = parts[0][:40]

            # التحقق مما إذا كانت المباراة قد انتهت
            if 'انتهت' in text or 'FT' in (match.get('class', []) or []):
                match_id = hash(text[:80])
                if match_id not in sent_alerts:
                    # محاولة استخراج أسماء الفريقين بشكل نظيف
                    teams = [t.strip() for t in text.split() if len(t) > 2 and t not in ['انتهت', 'FT', 'المباراة', 'البطولة', 'الدوري']]
                    if len(teams) >= 2:
                        match_name = f"{teams[0]} vs {teams[1]}"
                    else:
                        match_name = "مباراة مرصودة (فريقين)"
                    
                    format_and_send_alert(match_name, current_country, current_league, "FT")
                    sent_alerts.add(match_id)
                    
                    if len(sent_alerts) > 500:
                        sent_alerts.clear()
                        
    except Exception as e:
        print(f"Error scraping Kooora: {e}")

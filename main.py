def fetch_kooora_matches():
    global sent_matches
    print("بدء عملية فحص موقع كووورة للمباريات...", flush=True)
    try:
        url = "https://www.kooora.com/?matches=today"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Kooora HTTP Status: {response.status_code}", flush=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            matches = soup.find_all('div', class_='match')
            print(f"عدد المباريات المكتشفة: {len(matches)}", flush=True)
            
            for match in matches:
                text = match.text.strip()
                if "انتهت" in text or "FT" in text or "Full Time" in text:
                    match_name = text.replace('\n', ' - ')[:50]
                    if match_name not in sent_matches:
                        message = f"🚨 *تنبيه فجوة تأخير عاجل!*\n\nالمباراة: {match_name}\nالحالة: انتهت في كووورة ولكنها مستمرة في المنصة!\n⚡ سارع بالتحقق واغتنام الفرصة!"
                        send_telegram_message(message)
                        sent_matches.add(match_name)
        else:
            print(f"موقع كووورة رفض الاتصال برمز: {response.status_code}", flush=True)
            
        print("تم الانتهاء من دورة الفحص.", flush=True)
    except Exception as e:
        print(f"Scraping Error Details: {e}", flush=True)

def fetch_kooora_matches():
    matches_list = []
    try:
        url = "https://www.kooora.com/?matches=today"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # البحث عن عناصر المباريات الحقيقية في الموقع
            for match in soup.find_all('div', class_='match')[:5]:
                name = match.text.strip().replace('\n', ' - ')
                if len(name) > 5:
                    matches_list.append({
                        "name": name[:50],
                        "kooora_status": "Live",
                        "platforms": [{"name": "Tipwin", "status": "Active"}]
                    })
    except Exception as e:
        print(f"خطأ: {e}")
        
    return matches_list

import os
import json
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def setup_driver():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def get_chumtoto_venue(driver, url):
    """詳細ページから会場と時間を取得"""
    venue = "詳細を確認"
    time_info = " "
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # JSON-LDから抽出
        json_ld = soup.find('script', type='application/ld+json')
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if isinstance(data, dict):
                    if 'location' in data and 'name' in data['location']:
                        venue = data['location']['name']
                    if 'startDate' in data:
                        dt = datetime.fromisoformat(data['startDate'].replace('Z', '+00:00'))
                        time_info = dt.strftime('%H:%M~')
            except Exception:
                pass

        # フォールバックテーブル解析
        if venue == "詳細を確認" or time_info == " ":
            table = soup.find('table')
            if table:
                for row in table.find_all('tr'):
                    th = row.find('th')
                    td = row.find('td')
                    if th and td:
                        th_text = th.get_text(strip=True)
                        td_text = td.get_text(strip=True)
                        if "会場" in th_text:
                            venue = td_text
                        elif "時間" in th_text or "開場" in th_text:
                            time_info = td_text
    except Exception as e:
        print(f"詳細取得失敗: {url} -> {e}")
    return venue, time_info

if __name__ == "__main__":
    driver = setup_driver()
    events = []
    base_url = "https://chumtoto.jp/schedule/"
    
    print("🤖 【Step 1】ちゃむととのスケジュールを単独取得中...")
    try:
        driver.get(base_url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "full-calendar-day")))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        calendar_days = soup.find_all('div', class_='full-calendar-day')
        
        for day_div in calendar_days:
            date_class = day_div.get('class', [])
            date_str = None
            for c in date_class:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', c):
                    date_str = c
                    break
            if not date_str:
                continue
                
            event_items = day_div.find_all('div', class_='full-calendar-item')
            for item in event_items:
                link_tag = item.find('a')
                if link_tag:
                    title = link_tag.get_text(strip=True)
                    url = link_tag.get('href')
                    
                    if any(e['title'] == title and e['start'] == date_str for e in events):
                        continue
                    events.append({"title": title, "start": date_str, "url": url})
    except Exception as e:
        print(f"取得エラー: {e}")

    print(f"➡ ChumTotoのイベントを {len(events)} 件回収しました。各会場を解析中...")

    # 詳細ページの解析
    formatted_events = []
    for ev in events:
        print(f"解析中: {ev['title']}")
        venue, time_info = get_chumtoto_venue(driver, ev['url'])
        
        formatted_events.append({
            "date": ev['start'],
            "title": ev['title'].replace('【ちゃむ】', ''),  # ここで綺麗に成形
            "venue": venue,
            "time": time_info,
            "url": ev['url']
        })

    driver.quit()

    # ==========================================
    # 💡 通信せず、データをGAS用の形式のJSONファイルに書き出すだけ
    # ==========================================
    payload = {
        "action": "sync_schedule",
        "events": formatted_events
    }

    with open('schedule.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
        
    print("📁 中間ファイル schedule.json の作成が完了しました。")

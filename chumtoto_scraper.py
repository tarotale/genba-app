import os
import json
import time
import re
from datetime import datetime
import requests
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
    # 💡 GitHub Actions上のLinux環境でSeleniumを100%安定させるための必須オプションを追加
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
    
    print("🤖 ちゃむととのスケジュールを単独取得中...")
    try:
        driver.get(base_url)
        # 画面サイズが確保されたので、これで要素を見つけられるようになります
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
            "title": ev['title'],
            "venue": venue,
            "time": time_info,
            "url": ev['url']
        })

    driver.quit()

    # ==========================================
    # Googleスプレッドシート（GAS）への一発同期
    # ==========================================
    GAS_URL = "https://script.google.com/macros/s/AKfycbxTpsaay81w4DDRfjfui7pfmnlc4aDaOPJx_fy4Shf275gpnyUZ9R-ObhAWQOMVOwyP/exec"

    payload = {
        "action": "sync_schedule",
        "events": formatted_events
    }

    print("🚀 Googleスプレッドシートの『公式スケジュール』へ同期を送信中...")
    try:
        response = requests.post(GAS_URL, json=payload, headers={'Content-Type': 'text/plain'})
        print("同期結果:", response.text)
    except Exception as e:
        print(f"送信エラー: {e}")

    print("🎉 すべての単独同期工程が正常に終了しました！")

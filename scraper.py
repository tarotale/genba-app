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

# --- 共通セットアップ ---
def setup_driver():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def get_chumtoto_venue(driver, url):
    """詳細ページから会場と時間を抽出する"""
    venue = "詳細を確認"
    time_info = " "
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(1.5)  # 読み込み待機
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # 1. 構造化データの抽出 (JSON-LD)
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

        # 2. JSON-LDで取得できない場合のフォールバック
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
        print(f"詳細ページの取得失敗: {url} -> {e}")
    
    return venue, time_info

def scrape_chumtoto(driver):
    """ちゃむととのスケジュールスクレイピング"""
    events = []
    base_url = "https://chumtoto.jp/schedule/"
    print("ちゃむととのスケジュールを取得中...")
    try:
        driver.get(base_url)
        wait = WebDriverWait(driver, 10)
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
                    
                    # 重複チェック
                    if any(e['title'] == title and e['start'] == date_str for e in events):
                        continue
                        
                    events.append({
                        "title": title,  # カレンダー表示用に「【ちゃむ】」のプレフィックスを外してスッキリさせました
                        "start": date_str,
                        "url": url,
                        "group": "ChumToto"
                    })
    except Exception as e:
        print(f"ちゃむととの取得エラー: {e}")
    return events


# --- メイン実行処理 ---
if __name__ == "__main__":
    driver = setup_driver()
    
    # 1. ChumTotoのスケジュールだけを取得
    chumtoto_events = scrape_chumtoto(driver)
    print(f"ChumTotoのイベントを {len(chumtoto_events)} 件取得しました。詳細（会場等）を解析中...")

    # 2. 各イベントの会場と時間を取得
    for ev in chumtoto_events:
        if ev.get('url'):
            print(f"詳細解析中: {ev['title']}")
            venue, time_info = get_chumtoto_venue(driver, ev['url'])
            ev['venue'] = venue
            ev['time_info'] = time_info
        else:
            ev['venue'] = "詳細を確認"
            ev['time_info'] = ""

    driver.quit()

    # 3. ローカルの履歴管理データ(data.json)の更新
    old_data_dict = {}
    if os.path.exists('data.json'):
        try:
            with open('data.json', 'r', encoding='utf-8') as f:
                old_list = json.load(f)
                old_data_dict = {(ev['title'], ev['start']): ev.get('added_at') for ev in old_list}
        except Exception as e:
            print(f"前回のデータ読み込みに失敗しました: {e}")

    current_now = datetime.now().isoformat()
    for ev in chumtoto_events:
        key = (ev['title'], ev['start'])
        ev['added_at'] = old_data_dict.get(key, current_now)

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(chumtoto_events, f, ensure_ascii=False, indent=4)
    print("ローカルの data.json を更新しました。")


    # 4. Googleスプレッドシート（GAS）への自動同期
    # ★重要：ご自身の新デプロイ版GASウェブアプリURLに書き換えてください
    GAS_URL = "https://script.google.com/macros/s/AKfycbxTpsaay81w4DDRfjfui7pfmnlc4aDaOPJx_fy4Shf275gpnyUZ9R-ObhAWQOMVOwyP/exec"

    formatted_events = []
    for ev in chumtoto_events:
        date_str = ev['start'].split('T')[0] if 'T' in ev['start'] else ev['start']
        formatted_events.append({
            "date": date_str,
            "title": ev['title'],
            "venue": ev.get('venue', '詳細を確認'),
            "time": ev.get('time_info', ''),
            "url": ev.get('url', '')
        })

    payload = {
        "action": "sync_schedule",
        "events": formatted_events
    }

    if GAS_URL == "あなたの新しいGASデプロイURL":
        print("⚠️ GAS_URL が未設定のため、スプレッドシートへの同期をスキップしました。")
    else:
        print("Googleスプレッドシートの『公式スケジュール』シートへChumTotoのデータを同期中...")
        try:
            response = requests.post(GAS_URL, json=payload, headers={'Content-Type': 'text/plain'})
            print("同期結果:", response.text)
        except Exception as e:
            print(f"スプレッドシートへのデータ送信中にエラーが発生しました: {e}")

    print("すべての工程が正常に終了しました！")

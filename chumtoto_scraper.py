import os
import json
import time
import re
from datetime import datetime, timedelta
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

def get_detail_info(driver, url):
    """詳細ページから会場と時間を抽出する"""
    venue = "詳細を確認"
    time_info = ""
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # 1. 構造化タグ優先
        v_el = soup.select_one('.p-clubScheduleArticle__place__text span, .p-clubScheduleDetail__venue, .tribe-events-pro-venue__name, .tribe-venue')
        t_el = soup.select_one('.p-clubScheduleArticle__description__item, .p-clubScheduleDetail__time, .tribe-events-pro-full-date, .tribe-events-schedule')
        if v_el: venue = v_el.get_text(strip=True)
        if t_el: time_info = t_el.get_text(strip=True)
        
        # 2. 本文テキスト解析
        content = soup.select_one('.common__article, .article__content, .body, .c-clubWysiwyg, .tribe-events-single-event-description, .p-clubScheduleArticle__description')
        
        if content:
            # パターンA: 見出し(h4, strong)と内容が分かれている
            for tag in content.find_all(['h4', 'strong']):
                label = tag.get_text(strip=True)
                
                data = ""
                if tag.next_sibling and isinstance(tag.next_sibling, str):
                    data = tag.next_sibling.strip()
                
                if not data or data in ["：", ":"]:
                    next_el = tag.find_next(['p', 'span'])
                    if next_el: data = next_el.get_text(strip=True)

                if "時間" in label or "公演時間" in label:
                    time_info = data.replace("：", "").replace(":", "").strip()
                elif ("日時" in label) and not time_info:
                    time_info = data.replace("：", "").replace(":", "").strip()
                elif "場所" in label or "会場" in label:
                    venue = data.replace("：", "").replace(":", "").strip()

            # パターンB: 1つのタグ内に改行区切りで書かれている（ChumToto用）
            if venue == "詳細を確認" or not time_info or time_info == "":
                lines = [line.strip() for line in content.get_text("\n").split("\n") if line.strip()]
                for line in lines:
                    if any(k in line for k in ["■場所", "■会場", "会場：", "会場:", "場所：", "場所:"]):
                        res = re.sub(r'^(■場所|■会場|会場|場所)[：:]\s*', '', line).strip()
                        if res: venue = res
                    if any(k in line for k in ["■時間", "時間：", "時間:", "公演時間"]):
                        res = re.sub(r'^(■時間|公演時間|時間)[：:]\s*', '', line).strip()
                        if res: time_info = res

        if not time_info:
            dt_el = soup.select_one('.p-clubScheduleArticle__dateTime span, .article__date')
            if dt_el: 
                time_info = re.sub(r'^\d{4}[/.]\d{2}[/.]\d{2}\(.\)\s*', '', dt_el.get_text(strip=True))

    except Exception as e:
        print(f"Detail parse warning at {url}: {e}")
    
    return venue, time_info

def scrape_chumtoto_only(driver, url):
    """ChumToto専用：一覧からURLを抜いて詳細解析（確実版ロジック）"""
    events = []
    current_url = url
    while current_url:
        try:
            print(f"ChumToto 取得中: {current_url}")
            driver.get(current_url)
            time.sleep(8)
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            days = soup.select('.tribe-events-calendar-month__day')
            links_to_crawl = []
            
            for day in days:
                time_tag = day.select_one('time.tribe-events-calendar-month__day-date-daynum')
                if not time_tag or not time_tag.has_attr('datetime'): continue
                date_str = time_tag['datetime']
                event_links = day.select('a.tribe-events-calendar-month__multiday-event-hidden-link, a.tribe-events-calendar-month__calendar-event-title-link')
                
                for link in event_links:
                    href = link.get('href')
                    title_el = link.select_one('h3') or link
                    title = title_el.get_text(strip=True)
                    if title and href:
                        links_to_crawl.append({"title": title, "url": href, "date": date_str})
            
            for item in links_to_crawl:
                v, tm = get_detail_info(driver, item['url'])
                
                # 新カレンダー用に「[ChumToto]」や「【ちゃむ】」を外したピュアなタイトル、GAS用のキー名(date, venue, time)に成形
                events.append({
                    "date": item['date'],
                    "title": item['title'],
                    "venue": v,
                    "time": tm,
                    "url": item['url']
                })
                
            next_link = soup.select_one('a.tribe-events-c-top-bar__nav-link--next, a.tribe-common-c-btn-icon--caret-right')
            current_url = next_link.get('href') if next_link and next_link.has_attr('href') else None
        except Exception as e:
            print(f"一覧取得エラー: {e}")
            break
            
    return events

def main():
    driver = setup_driver()
    
    # ChumTotoのスケジュールだけをピンポイント取得
    chumtoto_events = scrape_chumtoto_only(driver, "https://chumtoto.jp/schedule/")
    
    driver.quit()

    # 重複排除
    unique_events = list({(ev['title'], ev['date']): ev for ev in chumtoto_events}.values())

    # ==========================================
    # 💡 外部通信は一切せず、GAS要求フォーマットでJSON保存のみ行う
    # ==========================================
    payload = {
        "action": "sync_schedule",
        "events": unique_events
    }

    with open('schedule.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"📁 中間ファイルの作成が完了。合計 {len(unique_events)} 件のChumTotoスケジュールを記録しました。")

if __name__ == "__main__":
    main()

import streamlit as st
from google import genai
from google.genai import types
import json
import pandas as pd
import plotly.express as px
import time
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse
from datetime import datetime, timedelta

st.set_page_config(page_title="ホテル口コミ分析", layout="wide")
st.title("🏨 ホテル口コミ分析 - 【爆速】キーワード絞り込み版")

# --- 設定エリア ---
with st.sidebar:
    st.header("設定")
    st.success("🚀 有料枠：キーワードフィルタリング×爆速AI")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索ページ数", min_value=1, max_value=30, value=15)
    
    st.subheader("🔍 絞り込みキーワード")
    keywords_str = st.text_area("以下のワードが含まれる口コミのみAI分析します", "ホコリ,カビ,汚れ,清掃,不潔,ゴミ,臭い,汚い,掃除,髪の毛,水回り")
    keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
    
    analyze_btn = st.button("🚀 爆速分析を開始", type="primary")

# --- スクレイピング関数 ---
def scrape_jalan_reviews(base_url, max_pages, keywords):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    all_count = 0
    filtered_reviews = []
    seen_texts = set()
    debug_log = []
    current_url = base_url
    
    try:
        for page in range(max_pages):
            response = requests.get(current_url, headers=headers, timeout=10)
            response.raise_for_status()
            response.encoding = response.apparent_encoding 
            soup = BeautifulSoup(response.text, 'html.parser')
            
            comments = soup.find_all(['p', 'div'], class_=re.compile(r'jlnpc-kuchikomiCassette__postBody|jln-review-detail__text|kuchikomi-text'))
            if not comments: break
            
            added_this_page = 0
            for comment in comments:
                text = comment.get_text(strip=True)
                if len(text) > 10 and text not in seen_texts:
                    seen_texts.add(text)
                    all_count += 1
                    # ここでキーワードフィルタリング！
                    if any(k in text for k in keywords):
                        filtered_reviews.append({"text": text})
                        added_this_page += 1
            
            debug_log.append(f"P{page+1}: {added_this_page}件ヒット (累計:{len(filtered_reviews)})")
            
            # ページ送り解析
            next_link = soup.find('a', class_=re.compile(r'(?i)next')) or soup.find('a', string=re.compile(r'.*次へ.*'))
            if next_link:
                match = re.search(r"selectPage\('(\d+)','(\d+)'\)", next_link.get('onclick', ''))
                if match:
                    n_idx, n_page = match.group(1), match.group(2)
                    parsed = urllib.parse.urlparse(current_url)
                    path = re.sub(r'\d+\.(html|HTML)$', '', parsed.path, flags=re.IGNORECASE)
                    if not path.endswith('/'): path += '/'
                    current_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, f"{path}{n_page}.HTML", parsed.params, urllib.parse.urlencode({'screenId':'UWW3701', 'idx':n_idx}, doseq=True), parsed.fragment))
                    time.sleep(0.05)
                else: break
            else: break
    except Exception as e:
        st.error(f"スクレイピング失敗: {e}")
    return filtered_reviews, all_count, "\n".join(debug_log)

# --- メイン処理 ---
if analyze_btn and target_input:
    client = genai.Client(api_key=GEMINI_API_KEY)
    ACTIVE_MODEL = "models/gemini-2.5-flash"

    # 1. スクレイピング & キーワード抽出
    with st.status("🔍 爆速スクレイピング中...", expanded=True) as status:
        start_scrape = time.time()
        filtered_reviews, total_scraped, log = scrape_jalan_reviews(target_input, max_pages, keywords)
        scrape_time = time.time() - start_scrape
        status.update(label=f"✅ 抽出完了：全{total_scraped}件中、{len(filtered_reviews)}件を「当たり」として抽出（{scrape_time:.1f}秒）", state="complete")

    if not filtered_reviews:
        st.warning("指定したキーワードに一致する不満は見つかりませんでした。"); st.stop()

    # 2. AI分析（時間計測 & 予測つき）
    st.info(f"🤖 AI分析を開始：対象 {len(filtered_reviews)} 件")
    
    # 時間表示用コンテナ
    timer_container = st.empty()
    progress_bar = st.progress(0)
    
    results = []
    batch_size = 100 # 有料枠なら一気に100件！
    start_ai = time.time()
    
    total_batches = (len(filtered_reviews) + batch_size - 1) // batch_size

    for i in range(0, len(filtered_reviews), batch_size):
        # タイマー更新
        elapsed = time.time() - start_ai
        current_batch = (i // batch_size) + 1
        eta = (elapsed / current_batch) * (total_batches - current_batch) if current_batch > 1 else (total_batches * 2.0)
        
        timer_container.markdown(f"⏱ **経過時間:** `{elapsed:.1f}秒` | ⏳ **完了予測まであと:** `{eta:.1f}秒`")
        
        batch = filtered_reviews[i:i + batch_size]
        input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
        
        prompt = (
            "清掃ロボット営業マンとして、以下の不満が含まれる可能性のある口コミをJSON配列で分析。 "
            "1. id, 2. is_cleaning(true/false), 3. category, 4. robot_match, 5. score(1-5), 6. summary(15字) "
            f"【入力】{json.dumps(input_data, ensure_ascii=False)}"
        )
        
        try:
            response = client.models.generate_content(
                model=ACTIVE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            raw_text = re.sub(r'^```(json)?\s*|\s*```$', '', response.text.strip())
            batch_analysis = json.loads(raw_text)
            
            for analysis in batch_analysis:
                idx = analysis.get("id")
                if idx is not None and idx < len(batch):
                    results.append({
                        "内容": batch[idx]['text'],
                        "清掃関連": "あり" if analysis.get('is_cleaning') else "なし",
                        "カテゴリ": analysis.get('category', '-'),
                        "ロボット適性": analysis.get('robot_match', '-'),
                        "スコア": analysis.get('score', 0),
                        "要約": analysis.get('summary', '-')
                    })
        except Exception as e:
            st.error(f"AI分析エラー: {e}")
        
        progress_bar.progress(min((i + batch_size) / len(filtered_reviews), 1.0))
        time.sleep(0.05)

    total_ai_time = time.time() - start_ai
    timer_container.markdown(f"✅ **分析完了！ 総所要時間:** `{total_ai_time:.1f}秒`")

    # 3. 結果表示
    df = pd.DataFrame(results).fillna("-")
    df_clean = df[df["清掃関連"] == "あり"]
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("スクレイピング総数", f"{total_scraped}件")
    c2.metric("キーワード該当数", f"{len(filtered_reviews)}件")
    c3.metric("AI判定・清掃課題", f"{len(df_clean)}件")

    if not df_clean.empty:
        col_left, col_right = st.columns([1, 1])
        with col_left:
            st.plotly_chart(px.bar(df_clean['カテゴリ'].value_counts().reset_index(), x='count', y='カテゴリ', orientation='h', title="課題カテゴリ"))
        with col_right:
            st.plotly_chart(px.pie(df_clean, names='ロボット適性', title="ロボット導入の期待度"))
        
        st.subheader("📋 清掃課題の一覧（アタックリスト）")
        st.dataframe(df_clean, use_container_width=True)
    else:
        st.warning("清掃に関する課題は見つかりませんでした。キーワード設定を調整してみてください。")

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
from datetime import timedelta

st.set_page_config(page_title="ホテル口コミ分析", layout="wide")
st.title("🏨 ホテル口コミ分析 - 有料版（爆速リミッター解除）")

with st.sidebar:
    st.header("設定")
    st.success("🚀 有料枠（Paid Tier）稼働中：\nGemini 3 Flashによる爆速分析モード")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索する最大ページ数（※1ページ最大30件）", min_value=1, max_value=30, value=15)
    analyze_btn = st.button("🚀 爆速で抽出＆分析を開始", type="primary")

def scrape_jalan_reviews(base_url, max_pages):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    reviews = []
    seen_texts = set()
    debug_log = []
    current_url = base_url
    
    try:
        for page in range(max_pages):
            debug_log.append(f"【{page+1}ページ目】アクセス先: {current_url}")
            response = requests.get(current_url, headers=headers, timeout=15)
            response.raise_for_status() 
            response.encoding = response.apparent_encoding 
            soup = BeautifulSoup(response.text, 'html.parser')
            
            comments = soup.find_all(['p', 'div'], class_=re.compile(r'jlnpc-kuchikomiCassette__postBody|jln-review-detail__text|kuchikomi-text'))
            
            if not comments:
                debug_log.append(f"⚠️ {page+1}ページ目で口コミが見つかりませんでした。")
                break 
                
            added_in_this_page = 0
            for comment in comments:
                text = comment.get_text(strip=True)
                if len(text) > 10 and text not in seen_texts:
                    reviews.append({"text": text, "date": "日付不明"})
                    seen_texts.add(text)
                    added_in_this_page += 1
            
            if added_in_this_page == 0: break

            # ページ送り
            next_url = None
            next_link = soup.find('a', class_=re.compile(r'(?i)next'))
            if next_link:
                onclick_attr = next_link.get('onclick', '')
                match = re.search(r"selectPage\('(\d+)','(\d+)'\)", onclick_attr)
                if match:
                    next_idx, next_page_num = match.group(1), match.group(2)
                    parsed = urllib.parse.urlparse(current_url)
                    path = re.sub(r'\d+\.html$', '', parsed.path, flags=re.IGNORECASE)
                    if not path.endswith('/'): path += '/'
                    next_path = f"{path}{next_page_num}.HTML"
                    
                    query_params = urllib.parse.parse_qs(parsed.query)
                    query_params['idx'] = [next_idx]
                    if 'screenId' in query_params: query_params['screenId'] = ['UWW3701']
                    new_query = urllib.parse.urlencode(query_params, doseq=True)
                    next_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, next_path, parsed.params, new_query, parsed.fragment))
                        
            if next_url:
                current_url = next_url
                time.sleep(0.1) # 有料版なのでスクレイピングの負荷調整のみ
            else: break 
                
    except Exception as e:
        debug_log.append(f"🚨 スクレイピングエラー: {str(e)}")
        
    return reviews, "\n".join(debug_log)

if analyze_btn and target_input:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    
    with st.spinner("🔍 データを抽出中..."):
        valid_reviews, debug_text = scrape_jalan_reviews(target_input, max_pages)
        actual_count = len(valid_reviews)

    if actual_count == 0:
        st.error("有効なデータが取得できませんでした。"); st.stop()

    st.info(f"🤖 最新AI(Gemini 3 Flash)で {actual_count} 件を爆速分析中...")
    
    progress_info = st.empty()
    progress_bar = st.progress(0)
    
    results = []
    cleaning_count = 0
    batch_size = 50 
    start_time = time.time()
    
    for i in range(0, actual_count, batch_size):
        progress_info.write(f"📊 分析進捗: {min(i + batch_size, actual_count)} / {actual_count} 件")
        
        batch = valid_reviews[i:i + batch_size]
        input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
        
        prompt = f"""
        あなたは清掃ロボット営業マンです。以下の複数の口コミを分析し、指定されたJSONの配列形式で回答してください。
        1. id, 2. is_cleaning, 3. category, 4. robot_match, 5. score, 6. summary
        【入力データ】
        {json.dumps(input_data, ensure_ascii=False)}
        """
        
        try:
            # 最新モデル Gemini 3 Flash を指定
            response = ai_client.models.generate_content(
                model='gemini-3-flash',
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            
            raw_text = response.text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            
            batch_analysis = json.loads(raw_text)
            for analysis in batch_analysis:
                idx = analysis.get("id")
                if idx is not None and idx < len(batch):
                    original_review = batch[idx]
                    if analysis.get('is_cleaning'): cleaning_count += 1
                    results.append({
                        "時期": "-", "内容": original_review['text'],
                        "清掃関連": "あり" if analysis.get('is_cleaning') else "なし",
                        "カテゴリ": analysis.get('category', '-'),
                        "ロボット適性": analysis.get('robot_match', '-'),
                        "スコア": analysis.get('score', 0),
                        "要約": analysis.get('summary', '-')
                    })
            
            # 有料枠なのでウェイトを最小化
            time.sleep(0.2)
        except Exception as e:
            st.error(f"AI分析エラー: {e}")
            break
        
        progress_bar.progress(min((i + batch_size) / actual_count, 1.0))
        
    st.success(f"🎉 全 {actual_count} 件の分析が完了しました！（所要時間: {int(time.time() - start_time)}秒）")

    # 結果表示
    st.divider()
    col1, col2 = st.columns(2)
    col1.metric("取得した口コミ総数", f"{actual_count}件")
    col2.metric("清掃関連の課題数", f"{cleaning_count}件")

    df = pd.DataFrame(results)
    df_clean = df[df["清掃関連"] == "あり"]
    
    if not df_clean.empty:
        g_col1, g_col2 = st.columns(2)
        with g_col1:
            st.plotly_chart(px.bar(df_clean['カテゴリ'].value_counts().reset_index(), x='count', y='カテゴリ', title="課題カテゴリ", orientation='h'))
        with g_col2:
            st.plotly_chart(px.pie(df_clean, names='ロボット適性', title="ロボット導入の期待度"))
    
    st.subheader("📋 清掃課題の一覧")
    st.dataframe(df_clean, use_container_width=True)

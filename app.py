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
st.title("🏨 ホテル口コミ分析 - 安定＆詳細デバッグ版")

with st.sidebar:
    st.header("設定")
    st.success("🚀 有料枠（Paid Tier）最適化稼働中")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索する最大ページ数（※1ページ最大30件）", min_value=1, max_value=30, value=15)
    analyze_btn = st.button("🚀 抽出＆分析を開始", type="primary")

def scrape_jalan_reviews(base_url, max_pages):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    reviews, seen_texts, debug_log = [], set(), []
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
                debug_log.append(f"⚠️ {page+1}ページ目で口コミ要素が見つかりませんでした。")
                break
            
            added_in_this_page = 0
            for comment in comments:
                text = comment.get_text(strip=True)
                if len(text) > 10 and text not in seen_texts:
                    reviews.append({"text": text, "date": "日付不明"})
                    seen_texts.add(text)
                    added_in_this_page += 1
            
            debug_log.append(f"→ 新規口コミ {added_in_this_page} 件取得")
            if added_in_this_page == 0: break

            # ページ送り（JS解析）
            next_url = None
            next_link = soup.find('a', class_=re.compile(r'(?i)next')) or soup.find('a', string=re.compile(r'.*次へ.*'))
            if next_link:
                onclick = next_link.get('onclick', '')
                match = re.search(r"selectPage\('(\d+)','(\d+)'\)", onclick)
                if match:
                    next_idx, next_page = match.group(1), match.group(2)
                    parsed = urllib.parse.urlparse(current_url)
                    path = re.sub(r'\d+\.html$', '', parsed.path, flags=re.IGNORECASE)
                    if not path.endswith('/'): path += '/'
                    next_path = f"{path}{next_page}.HTML"
                    q = urllib.parse.parse_qs(parsed.query)
                    q['idx'] = [next_idx]
                    if 'screenId' in q: q['screenId'] = ['UWW3701']
                    new_q = urllib.parse.urlencode(q, doseq=True)
                    next_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, next_path, parsed.params, new_q, parsed.fragment))
                        
            if next_url:
                current_url = next_url
                time.sleep(0.1)
            else: 
                debug_log.append("「次へ」リンクがなくなったため終了")
                break
    except Exception as e:
        debug_log.append(f"🚨 エラー: {str(e)}")
    return reviews, "\n".join(debug_log)

if analyze_btn and target_input:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    
    # --- ステップ1: スクレイピング ---
    with st.status("🔍 口コミデータを探索・抽出中...", expanded=True) as status:
        valid_reviews, debug_text = scrape_jalan_reviews(target_input, max_pages)
        actual_count = len(valid_reviews)
        status.update(label=f"✅ 抽出完了（実件数: {actual_count}件）", state="complete", expanded=False)

    # --- 復活したデバッグ機能 ---
    with st.expander("🛠 【デバッグ】抽出された生データとログを確認する", expanded=False):
        st.write("AI分析に回す前のデータです。正しく取れているか確認してください。")
        if actual_count > 0:
            st.dataframe(pd.DataFrame(valid_reviews))
        st.text_area("実行ログ", debug_text, height=200)

    if actual_count == 0:
        st.error("有効なデータが取得できませんでした。URLを確認してください。")
        st.stop()

    # --- ステップ2: AI分析 ---
    st.info(f"🤖 AI(Gemini 1.5 Flash)で {actual_count} 件を分析します...")
    progress_info = st.empty()
    progress_bar = st.progress(0)
    
    results = []
    batch_size = 50 
    expected_cols = ["時期", "内容", "清掃関連", "カテゴリ", "ロボット適性", "スコア", "要約"]
    
    for i in range(0, actual_count, batch_size):
        progress_info.write(f"📊 分析進捗: {min(i + batch_size, actual_count)} / {actual_count} 件")
        batch = valid_reviews[i:i + batch_size]
        input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
        
        prompt = f"""あなたは清掃ロボット営業マンです。以下の口コミを分析し、JSON配列形式で回答してください。
        1. id, 2. is_cleaning, 3. category, 4. robot_match, 5. score, 6. summary
        【入力データ】
        {json.dumps(input_data, ensure_ascii=False)}"""
        
        try:
            # 2.0が404になるため、最も安定している1.5-flashを使用
            response = ai_client.models.generate_content(
                model='gemini-1.5-flash',
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
                    results.append({
                        "時期": "-", "内容": batch[idx]['text'],
                        "清掃関連": "あり" if analysis.get('is_cleaning') else "なし",
                        "カテゴリ": analysis.get('category', '-'),
                        "ロボット適性": analysis.get('robot_match', '-'),
                        "スコア": analysis.get('score', 0),
                        "要約": analysis.get('summary', '-')
                    })
            time.sleep(0.2)
        except Exception as e:
            st.error(f"AI分析中にエラーが発生しました: {e}")
            break
        progress_bar.progress(min((i + batch_size) / actual_count, 1.0))
        
    st.success("🎉 分析がすべて完了しました！")
    st.divider()

    # --- ステップ3: 結果表示 ---
    # 最初から期待される列を持つDataFrameを作成してKeyErrorを防止
    df = pd.DataFrame(results, columns=expected_cols).fillna("-")
    df_clean = df[df["清掃関連"] == "あり"]
    
    col1, col2 = st.columns(2)
    col1.metric("取得した口コミ総数", f"{actual_count}件")
    col2.metric("清掃関連の課題数", f"{len(df_clean)}件")

    if not df_clean.empty:
        g_col1, g_col2 = st.columns(2)
        with g_col1:
            st.plotly_chart(px.bar(df_clean['カテゴリ'].value_counts().reset_index(), x='count', y='カテゴリ', title="課題カテゴリの内訳", orientation='h'))
        with g_col2:
            st.plotly_chart(px.pie(df_clean, names='ロボット適性', title="ロボット導入の期待度"))
        
        st.subheader("📋 清掃に関する課題が指摘された口コミ")
        st.dataframe(df_clean, use_container_width=True)
        
        st.subheader("📝 すべての分析結果")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("清掃に関する明確な課題は見当たりませんでした。")
        st.subheader("📝 すべての分析結果")
        st.dataframe(df, use_container_width=True)

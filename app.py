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

# ページ設定
st.set_page_config(page_title="ホテル口コミ分析", layout="wide")
st.title("🏨 ホテル口コミ分析 - 【営業即戦力】爆速完成版")

# --- 設定エリア ---
with st.sidebar:
    st.header("設定")
    st.success("🚀 有料枠（Paid Tier）リミッター解除稼働中")
    if "GEMINI_API_KEY" in st.secrets:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    else:
        GEMINI_API_KEY = st.text_input("API KEY", type="password")
    
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索ページ数（最大30）", min_value=1, max_value=30, value=15)
    analyze_btn = st.button("🚀 抽出＆分析を開始", type="primary")

# --- スクレイピング関数 ---
def scrape_jalan_reviews(base_url, max_pages):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    reviews, seen_texts, debug_log = [], set(), []
    current_url = base_url
    try:
        for page in range(max_pages):
            debug_log.append(f"【{page+1}ページ目】アクセス: {current_url}")
            response = requests.get(current_url, headers=headers, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding 
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 口コミ要素抽出
            comments = soup.find_all(['p', 'div'], class_=re.compile(r'jlnpc-kuchikomiCassette__postBody|jln-review-detail__text|kuchikomi-text'))
            if not comments: break
            
            added = 0
            for comment in comments:
                text = comment.get_text(strip=True)
                if len(text) > 10 and text not in seen_texts:
                    reviews.append({"text": text})
                    seen_texts.add(text)
                    added += 1
            
            debug_log.append(f"→ 新規 {added} 件取得")
            if added == 0: break

            # ページ送りJS解析（.HTML固定）
            next_link = soup.find('a', class_=re.compile(r'(?i)next')) or soup.find('a', string=re.compile(r'.*次へ.*'))
            if next_link:
                onclick = next_link.get('onclick', '')
                match = re.search(r"selectPage\('(\d+)','(\d+)'\)", onclick)
                if match:
                    n_idx, n_page = match.group(1), match.group(2)
                    parsed = urllib.parse.urlparse(current_url)
                    path = re.sub(r'\d+\.(html|HTML)$', '', parsed.path, flags=re.IGNORECASE)
                    if not path.endswith('/'): path += '/'
                    current_url = urllib.parse.urlunparse((
                        parsed.scheme, parsed.netloc, f"{path}{n_page}.HTML",
                        parsed.params, urllib.parse.urlencode({'screenId':'UWW3701', 'idx':n_idx}, doseq=True), parsed.fragment
                    ))
                    time.sleep(0.1)
                else: break
            else: break
    except Exception as e:
        debug_log.append(f"🚨 抽出エラー: {str(e)}")
    return reviews, "\n".join(debug_log)

# --- メイン処理 ---
if analyze_btn and target_input:
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 診断結果に基づきIDを固定
    ACTIVE_MODEL = "models/gemini-2.5-flash"

    # 1. 抽出
    with st.status("🔍 データを抽出中...", expanded=True) as status:
        valid_reviews, debug_text = scrape_jalan_reviews(target_input, max_pages)
        actual_count = len(valid_reviews)
        status.update(label=f"✅ 抽出完了（{actual_count}件）", state="complete")

    # 2. デバッグ表示
    with st.expander("🛠 詳細デバッグ（生データ・ログ）", expanded=False):
        if actual_count > 0: st.dataframe(pd.DataFrame(valid_reviews))
        st.text_area("ログ", debug_text, height=150)

    if actual_count == 0:
        st.error("有効なデータが取れませんでした。URLを確認してください。")
        st.stop()

    # 3. AI分析（爆速モード）
    st.info(f"🤖 AI ({ACTIVE_MODEL}) で爆速分析中...")
    progress_bar = st.progress(0)
    results = []
    batch_size = 50 

    for i in range(0, actual_count, batch_size):
        batch = valid_reviews[i:i + batch_size]
        input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
        
        prompt = (
            "清掃ロボット営業マンとして、以下の口コミをJSON配列で分析してください。\n"
            "1. id, 2. is_cleaning(true/false), 3. category, 4. robot_match, 5. score, 6. summary\n"
            f"【入力】{json.dumps(input_data, ensure_ascii=False)}"
        )
        
        try:
            response = client.models.generate_content(
                model=ACTIVE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            
            raw_text = response.text.strip()
            # 不要なコードブロックを削除
            raw_text = re.sub(r'^```(json)?\s*', '', raw_text)
            raw_text = re.sub(r'\s*```$', '', raw_text)
            
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
            st.error(f"分析エラー (バッチ {i}): {e}")
        
        progress_bar.progress(min((i + batch_size) / actual_count, 1.0))
        time.sleep(0.1) # 有料枠の爆速設定

    # 4. 結果表示
    if results:
        df = pd.DataFrame(results, columns=["内容", "清掃関連", "カテゴリ", "ロボット適性", "スコア", "要約"]).fillna("-")
        df_clean = df[df["清掃関連"] == "あり"]
        
        st.success(f"🎉 分析完了！ 清掃課題: {len(df_clean)}件")
        st.divider()
        
        col1, col2 = st.columns(2)
        col1.metric("分析総数", f"{actual_count}件")
        col2.metric("ターゲット件数", f"{len(df_clean)}件")

        if not df_clean.empty:
            c1, c2 = st.columns(2)
            with c1: st.plotly_chart(px.bar(df_clean['カテゴリ'].value_counts().reset_index(), x='count', y='カテゴリ', orientation='h', title="課題カテゴリ"))
            with c2: st.plotly_chart(px.pie(df_clean, names='ロボット適性', title="ロボット適性"))
            
            st.subheader("📋 清掃課題の一覧（アタックリスト）")
            st.dataframe(df_clean, use_container_width=True)
        else:
            st.warning("清掃課題は見当たりませんでした。")
        
        st.subheader("📝 全分析データ")
        st.dataframe(df, use_container_width=True)

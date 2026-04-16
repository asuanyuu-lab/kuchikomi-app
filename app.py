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

st.set_page_config(page_title="ホテル口コミ分析", layout="wide")
st.title("🏨 ホテル口コミ分析 - 【最終解決】モデル自動検知版")

with st.sidebar:
    st.header("設定")
    st.success("🚀 有料枠：モデル自動選択モード搭載")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索ページ数", min_value=1, max_value=30, value=15)
    analyze_btn = st.button("🚀 分析を開始", type="primary")

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
            comments = soup.find_all(['p', 'div'], class_=re.compile(r'jlnpc-kuchikomiCassette__postBody|jln-review-detail__text|kuchikomi-text'))
            if not comments: break
            
            added = 0
            for comment in comments:
                text = comment.get_text(strip=True)
                if len(text) > 10 and text not in seen_texts:
                    reviews.append({"text": text}); seen_texts.add(text); added += 1
            debug_log.append(f"→ 新規 {added} 件")
            if added == 0: break

            # ページ送り解析
            next_link = soup.find('a', class_=re.compile(r'(?i)next')) or soup.find('a', string=re.compile(r'.*次へ.*'))
            if next_link:
                match = re.search(r"selectPage\('(\d+)','(\d+)'\)", next_link.get('onclick', ''))
                if match:
                    n_idx, n_page = match.group(1), match.group(2)
                    parsed = urllib.parse.urlparse(current_url)
                    path = re.sub(r'\d+\.html$', '', parsed.path, flags=re.IGNORECASE)
                    if not path.endswith('/'): path += '/'
                    next_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, f"{path}{n_page}.HTML", parsed.params, urllib.parse.urlencode({'screenId':'UWW3701', 'idx':n_idx}, doseq=True), parsed.fragment))
                    current_url = next_url
                    time.sleep(0.1)
                else: break
            else: break
    except Exception as e:
        debug_log.append(f"🚨 スクレイピングエラー: {e}")
    return reviews, "\n".join(debug_log)

def get_best_model(client):
    """利用可能なモデルの中から最適なものを自動選択する"""
    try:
        available_models = [m.name for m in client.models.list()]
        # 2026年の優先順位
        priority = ['gemini-2.5-flash', 'gemini-3.1-flash', 'gemini-3-flash', 'gemini-1.5-flash']
        for p in priority:
            for m in available_models:
                if p in m: return m
        return available_models[0] # 見つからなければ最初のやつ
    except:
        return 'gemini-1.5-flash' # フォールバック

if analyze_btn and target_input:
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # モデルの自動検知
    with st.spinner("🤖 利用可能なAIモデルをスキャン中..."):
        best_model = get_best_model(client)
        st.write(f"📡 使用モデルを決定: `{best_model}`")

    # データ抽出
    with st.status("🔍 データを抽出中...", expanded=True) as status:
        valid_reviews, debug_text = scrape_jalan_reviews(target_input, max_pages)
        actual_count = len(valid_reviews)
        status.update(label=f"✅ 抽出完了（{actual_count}件）", state="complete")

    with st.expander("🛠 デバッグ情報", expanded=False):
        if actual_count > 0: st.dataframe(pd.DataFrame(valid_reviews))
        st.text_area("ログ", debug_text, height=150)

    if actual_count == 0: st.stop()

    # AI分析
    st.info(f"🤖 分析を開始します...")
    progress_bar = st.progress(0)
    results = []
    batch_size = 50

    for i in range(0, actual_count, batch_size):
        batch = valid_reviews[i:i + batch_size]
        input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
        prompt = f"清掃ロボット営業マンとしてJSON配列で分析。1.id, 2.is_cleaning, 3.category, 4.robot_match, 5.score, 6.summary\n【入力】{json.dumps(input_data, ensure_ascii=False)}"
        
        try:
            response = client.models.generate_content(
                model=best_model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            raw_text = response.text.strip()
            if "
http://googleusercontent.com/immersive_entry_chip/0

もしこれでも「モデルが見つからない」という場合は、**AI Studioの「APIキー」がまだそのプロジェクトの「Generative Language API」と完全に紐付いていない**可能性があります。その場合は、画面に出るログ（スキャン結果）を教えてください。すぐに次の手を打ちます！

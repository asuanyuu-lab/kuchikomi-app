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
st.title("🏨 ホテル口コミ分析 - 【完全版】自動復旧＆詳細デバッグ搭載")

with st.sidebar:
    st.header("設定")
    st.success("🚀 有料枠（Paid Tier）リミッター解除モード")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索ページ数（最大30）", min_value=1, max_value=30, value=15)
    analyze_btn = st.button("🚀 抽出＆分析を開始", type="primary")

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
            
            # 口コミ要素の抽出
            comments = soup.find_all(['p', 'div'], class_=re.compile(r'jlnpc-kuchikomiCassette__postBody|jln-review-detail__text|kuchikomi-text'))
            if not comments:
                debug_log.append("⚠️ このページに口コミが見つかりませんでした。")
                break
            
            added = 0
            for comment in comments:
                text = comment.get_text(strip=True)
                if len(text) > 10 and text not in seen_texts:
                    reviews.append({"text": text})
                    seen_texts.add(text)
                    added += 1
            
            debug_log.append(f"→ 新規 {added} 件（累計: {len(reviews)} 件）")
            if added == 0: break

            # ページ送りJS解析（いただいたHTML構造に対応）
            next_link = soup.find('a', class_=re.compile(r'(?i)next')) or soup.find('a', string=re.compile(r'.*次へ.*'))
            if next_link:
                onclick = next_link.get('onclick', '')
                match = re.search(r"selectPage\('(\d+)','(\d+)'\)", onclick)
                if match:
                    n_idx, n_page = match.group(1), match.group(2)
                    parsed = urllib.parse.urlparse(current_url)
                    # パスの正規化
                    path = re.sub(r'\d+\.HTML$', '', parsed.path, flags=re.IGNORECASE)
                    path = re.sub(r'\d+\.html$', '', path, flags=re.IGNORECASE)
                    if not path.endswith('/'): path += '/'
                    
                    next_url = urllib.parse.urlunparse((
                        parsed.scheme, parsed.netloc, f"{path}{n_page}.HTML",
                        parsed.params, 
                        urllib.parse.urlencode({'screenId':'UWW3701', 'idx':n_idx}, doseq=True), 
                        parsed.fragment
                    ))
                    current_url = next_url
                    time.sleep(0.1)
                else: break
            else: break
    except Exception as e:
        debug_log.append(f"🚨 スクレイピングエラー: {str(e)}")
    return reviews, "\n".join(debug_log)

def get_best_model(client):
    """APIキーで利用可能な最適なモデルを自動的に探す"""
    try:
        # モデルリストを取得
        models = [m.name for m in client.models.list()]
        # 優先順位（最新かつ軽量なFlash系をターゲット）
        targets = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.0-flash-exp']
        for target in targets:
            for m in models:
                if target in m: return m
        # 見つからない場合はリストの最初（または1.5-flash）を返す
        return models[0] if models else 'models/gemini-1.5-flash'
    except Exception as e:
        st.warning(f"モデルリストの取得に失敗しました。デフォルトを使用します。: {e}")
        return 'models/gemini-1.5-flash'

if analyze_btn and target_input:
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 📡 モデル自動検知
    with st.spinner("🤖 最適なAIモデルを検知中..."):
        active_model = get_best_model(client)
        st.caption(f"使用AI: `{active_model}`")

    # 🔍 STEP 1: スクレイピング
    with st.status("🔍 データを抽出中...", expanded=True) as status:
        valid_reviews, debug_text = scrape_jalan_reviews(target_input, max_pages)
        actual_count = len(valid_reviews)
        status.update(label=f"✅ 抽出完了（実数: {actual_count}件）", state="complete")

    # 🛠 デバッグ機能（復活）
    with st.expander("🛠 【詳細デバッグ】生データとスクレイピングログ", expanded=False):
        if actual_count > 0:
            st.write("### AI分析に渡される生テキスト")
            st.dataframe(pd.DataFrame(valid_reviews))
        st.write("### スクレイピング実行ログ")
        st.text_area("実行ログ内容", debug_text, height=200)

    if actual_count == 0:
        st.error("有効なデータが取得できませんでした。ログを確認してください。")
        st.stop()

    # 🤖 STEP 2: AI分析
    st.info(f"🤖 AI分析を開始します（バッチサイズ: 50）")
    progress_bar = st.progress(0)
    results = []
    batch_size = 50

    for i in range(0, actual_count, batch_size):
        batch = valid_reviews[i:i + batch_size]
        input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
        
        # プロンプトの構築
        prompt = (
            "あなたは清掃ロボット営業マンです。以下の口コミを分析し、指定されたJSON配列形式で回答してください。\n"
            "1. id, 2. is_cleaning(true/false), 3. category(床のホコリ・ゴミ/水回りの汚れ・カビ/ニオイ/ベッド周辺/その他清掃/清掃以外), "
            "4. robot_match(高/中/低/対象外), 5. score(1-5), 6. summary(15字以内)\n\n"
            f"【入力】\n{json.dumps(input_data, ensure_ascii=False)}"
        )
        
        try:
            response = client.models.generate_content(
                model=active_model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            
            # 文字列リテラルのエラーが出ないよう安全にパース
            raw_text = response.text.strip()
            # Markdownのコードブロック（```json ... ```）を排除
            raw_text = re.sub(r'^```json\s*', '', raw_text)
            raw_text = re.sub(r'^```\s*', '', raw_text)
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
            time.sleep(0.1) # 有料枠の爆速処理
            
        except Exception as e:
            st.error(f"AI分析エラー（バッチ {i}）: {e}")
            # エラーが出ても次に進める
        
        progress_bar.progress(min((i + batch_size) / actual_count, 1.0))

    # 📊 STEP 3: 結果表示
    df = pd.DataFrame(results, columns=["内容", "清掃関連", "カテゴリ", "ロボット適性", "スコア", "要約"]).fillna("-")
    df_clean = df[df["清掃関連"] == "あり"]
    
    st.divider()
    col1, col2 = st.columns(2)
    col1.metric("取得した口コミ総数", f"{actual_count}件")
    col2.metric("清掃課題が見つかった件数", f"{len(df_clean)}件")

    if not df_clean.empty:
        g_col1, g_col2 = st.columns(2)
        with g_col1:
            st.plotly_chart(px.bar(df_clean['カテゴリ'].value_counts().reset_index(), x='count', y='カテゴリ', title="指摘カテゴリの内訳", orientation='h'))
        with g_col2:
            st.plotly_chart(px.pie(df_clean, names='ロボット適性', title="ロボット導入による解決期待度"))
        
        st.subheader("📋 清掃課題の一覧（営業ターゲット）")
        st.dataframe(df_clean, use_container_width=True)
    else:
        st.warning("清掃に関する明確な課題は検出されませんでした。")

    st.subheader("📝 すべての分析生データ")
    st.dataframe(df, use_container_width=True)

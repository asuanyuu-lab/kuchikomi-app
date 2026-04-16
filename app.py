import streamlit as st
from google import genai
from google.genai import types
import json
import pandas as pd
import plotly.express as px
import time
import requests
from bs4 import BeautifulSoup
import urllib.parse
import re

# 1. ページ設定
st.set_page_config(page_title="ホテル口コミ分析", layout="wide")
st.title("🏨 ホテル口コミ分析 - 完全無料版（楽天ハイブリッド型）")

# サイドバー
with st.sidebar:
    st.header("設定")
    st.success("✨ 完全無料モード稼働中：\nホテル名検索、またはURLの直接入力のどちらでも分析可能です。")
    
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    st.markdown("### 抽出ターゲット")
    # ★ここが進化！名前でもURLでもOKな「ハイブリッド入力」
    target_input = st.text_input("ホテル名、または 楽天の口コミURL を入力", "FAV HOTEL 函館")
    analyze_btn = st.button("🚀 無料で口コミを抽出＆分析", type="primary")

def extract_id_from_text(text):
    """URLやテキストからHOTEL ID（数字）を抜き出す"""
    match = re.search(r'HOTEL/(\d+)', text, re.IGNORECASE)
    return match.group(1) if match else None

def get_rakuten_hotel_id(hotel_name):
    """ホテル名から楽天を検索してIDを探す（JSブロック対策強化）"""
    encoded_name = urllib.parse.quote(hotel_name)
    search_url = f"https://search.travel.rakuten.co.jp/ds/search/dtl?f_kw={encoded_name}"
    # ロボット感を消すための偽装ヘッダー
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    }
    
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # パターン1: リンク(aタグ)から探す
        for a in soup.find_all('a', href=True):
            hotel_id = extract_id_from_text(a['href'])
            if hotel_id: return hotel_id
            
        # パターン2: 楽天特有の「裏側のコード(script)」に隠されたIDを探す
        for script in soup.find_all('script'):
            if script.string:
                hotel_id = extract_id_from_text(script.string)
                if hotel_id: return hotel_id
    except Exception as e:
        print(f"検索エラー: {e}")
    return None

def scrape_rakuten_reviews(hotel_id):
    """IDを使って口コミページからデータを無料で引っこ抜く"""
    review_url = f"https://travel.rakuten.co.jp/HOTEL/{hotel_id}/review.html"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    
    reviews = []
    try:
        response = requests.get(review_url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        comments = soup.find_all('p', class_='commentSentence')
        dates = soup.find_all('span', class_='time')
        
        for i, comment in enumerate(comments):
            text = comment.get_text(strip=True)
            if text:
                date_str = dates[i].get_text(strip=True) if i < len(dates) else "日付不明"
                reviews.append({"text": text, "date": date_str})
    except Exception as e:
        print(f"抽出エラー: {e}")
    return reviews

# メイン処理
if analyze_btn and target_input:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    
    with st.status("🔍 ターゲットを解析中...", expanded=True) as status:
        
        # 1. URL入力か、ホテル名入力かを自動判定
        if target_input.startswith("http"):
            status.update(label="URLを検知しました。直接口コミを抽出します...")
            hotel_id = extract_id_from_text(target_input)
            display_name = "指定されたURLのホテル"
        else:
            status.update(label=f"「{target_input}」を楽天トラベルで検索中...")
            hotel_id = get_rakuten_hotel_id(target_input)
            display_name = target_input
            
        if not hotel_id:
            status.update(label="ホテルが見つかりませんでした。楽天の口コミURLを直接貼り付けてみてください。", state="error")
            st.stop()
            
        # 2. 無料スクレイピングの実行
        status.update(label="口コミページにアクセスし、データを抽出中...")
        valid_reviews = scrape_rakuten_reviews(hotel_id)

        if not valid_reviews:
            status.update(label="口コミが見つかりませんでした。まだ投稿されていないか、URLが間違っている可能性があります。", state="error")
            st.stop()

        status.update(label=f"計 {len(valid_reviews)} 件の口コミを抽出完了！AI分析を開始します...", state="running")
        
        # 3. AIによるまとめ読み分析
        results = []
        cleaning_count = 0
        progress_bar = st.progress(0)
        batch_size = 10 
        
        for i in range(0, len(valid_reviews), batch_size):
            batch = valid_reviews[i:i + batch_size]
            input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
            
            prompt = f"""
            あなたは清掃ロボット営業マンです。以下の複数の口コミを分析し、指定されたJSONの配列形式で回答してください。
            1. id: 入力されたid
            2. is_cleaning: (true/false) 清掃関連の不満か
            3. category: 「床のホコリ・ゴミ」「水回りの汚れ・カビ」「ニオイ」「ベッド周辺」「その他清掃」「清掃以外」
            4. robot_match: 清掃ロボットで解決可能か (高/中/低/対象外)
            5. score: 緊急度 (1〜5)
            6. summary: 15文字以内の要約

            【入力データ】
            {json.dumps(input_data, ensure_ascii=False)}
            """
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = ai_client.models.generate_content(
                        model='gemini-2.5-flash',
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
                            
                            if analysis.get('is_cleaning'): 
                                cleaning_count += 1
                                
                            results.append({
                                "時期": original_review.get('date', '-'),
                                "内容": original_review['text'],
                                "清掃関連": "あり" if analysis.get('is_cleaning') else "なし",
                                "カテゴリ": analysis.get('category', '-'),
                                "ロボット適性": analysis.get('robot_match', '-'),
                                "スコア": analysis.get('score', 0),
                                "要約": analysis.get('summary', '-')
                            })
                    
                    time.sleep(4) 
                    break 
                    
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        if attempt < max_retries - 1:
                            time.sleep(20)
                        else:
                            pass 
                    else:
                        break
            
            progress = min((i + batch_size) / len(valid_reviews), 1.0)
            progress_bar.progress(progress)
            
        status.update(label="すべての分析が完了しました！", state="complete")

    # ダッシュボード表示
    st.subheader(f"「{display_name}」の分析結果（抽出件数: {len(valid_reviews)}件）")
    
    col1, col2 = st.columns(2)
    col1.metric("取得した口コミ数", f"{len(valid_reviews)}件")
    col2.metric("清掃課題率", f"{(cleaning_count/len(valid_reviews)*100 if valid_reviews else 0):.1f}%")

    expected_columns = ["時期", "内容", "清掃関連", "カテゴリ", "ロボット適性", "スコア", "要約"]
    df = pd.DataFrame(results, columns=expected_columns).fillna("-")
    df_clean = df[df["清掃関連"] == "あり"]
    
    if not df_clean.empty:
        g_col1, g_col2 = st.columns(2)
        with g_col1:
            fig_bar = px.bar(df_clean['カテゴリ'].value_counts().reset_index(), 
                            x='count', y='カテゴリ', title="課題カテゴリの内訳",
                            labels={'count': '件数', 'カテゴリ': 'カテゴリ'}, orientation='h')
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with g_col2:
            fig_pie = px.pie(df_clean, names='ロボット適性', title="ロボット導入による解決期待度",
                           color='ロボット適性',
                           color_discrete_map={'高': '#EF4444', '中': '#F59E0B', '低': '#10B981', '対象外': '#9CA3AF'})
            st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.success("分析した口コミの中に、清掃に関する課題は見当たりませんでした。")

    st.subheader("📋 口コミ詳細一覧")
    st.dataframe(df, use_container_width=True)

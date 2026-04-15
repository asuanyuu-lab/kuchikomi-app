import streamlit as st
import googlemaps
from google import genai
from google.genai import types
import json
import pandas as pd
import plotly.express as px
import time

# 1. ページ設定とタイトル変更
st.set_page_config(page_title="ホテル口コミ分析", layout="wide")
st.title("🏨 ホテル口コミ分析 - オンデマンド診断")

# サイドバーでAPIキーとホテル名を設定
with st.sidebar:
    st.header("設定")
    MAPS_API_KEY = st.secrets["MAPS_API_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    target_hotel = st.text_input("分析対象のホテル名", "Fav 函館")
    analyze_btn = st.button("分析を実行", type="primary")

if analyze_btn and target_hotel:
    gmaps = googlemaps.Client(key=MAPS_API_KEY)
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    
    with st.spinner("データを収集中...（AIがまとめ読みして高速分析しています！）"):
        places_result = gmaps.places(query=target_hotel, language='ja')
        if not places_result['results']:
            st.error("指定されたホテルが見つかりませんでした。")
            st.stop()
            
        place_id = places_result['results'][0]['place_id']
        place_details = gmaps.place(place_id=place_id, fields=['name', 'rating', 'user_ratings_total', 'reviews'], language='ja')
        
        hotel_name = place_details['result'].get('name', '不明')
        total_rating = place_details['result'].get('rating', 0)
        review_count = place_details['result'].get('user_ratings_total', 0)
        raw_reviews = place_details['result'].get('reviews', [])

        # 空の口コミを除外
        valid_reviews = [r for r in raw_reviews if r.get('text')]

        if not valid_reviews:
            st.warning("直近の口コミが見つかりませんでした。")
            st.stop()

        # ダッシュボード上部のサマリー
        col1, col2, col3 = st.columns(3)
        col1.metric("Google総合評価", f"★{total_rating}")
        col2.metric("総口コミ数", f"{review_count}件")

        results = []
        cleaning_count = 0
        progress_bar = st.progress(0)
        
        batch_size = 10 # 一度にAIに渡す口コミの数
        
        for i in range(0, len(valid_reviews), batch_size):
            batch = valid_reviews[i:i + batch_size]
            input_data = [{"id": j, "text": r['text']} for j, r in enumerate(batch)]
            
            prompt = f"""
            あなたは清掃ロボット営業マンです。以下の【複数の口コミ】を一度に分析し、
            必ず指定されたJSONの「配列（リスト）形式」で回答してください。

            分析項目（各口コミに対して）：
            1. id: 入力されたidをそのまま返す
            2. is_cleaning: (true/false) 清掃関連の不満か
            3. category: 「床のホコリ・ゴミ」「水回りの汚れ・カビ」「ニオイ」「ベッド周辺」「その他清掃」「清掃以外」
            4. robot_match: 清掃ロボットで解決可能か (高/中/低/対象外)
            5. score: 緊急度 (1〜5)
            6. summary: 15文字以内の要約

            【入力データ（JSON）】
            {json.dumps(input_data, ensure_ascii=False)}

            【出力形式の例】
            [
              {{"id": 0, "is_cleaning": true, "category": "床のホコリ・ゴミ", "robot_match": "高", "score": 3, "summary": "床のホコリ残存"}},
              {{"id": 1, "is_cleaning": false, "category": "清掃以外", "robot_match": "対象外", "score": 1, "summary": "接客が良い"}}
            ]
            """
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = ai_client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    
                    # ★AIの回答に余計な記号(```json)が混ざっていたら除去する「お掃除機能」
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
                                "時期": original_review.get('relative_time_description', '-'),
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
                    error_msg = str(e)
                    if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                        if attempt < max_retries - 1:
                            time.sleep(20)
                        else:
                            pass 
                    else:
                        # 429以外のエラー（パース失敗など）はループを抜けてスキップ
                        break
            
            progress = min((i + batch_size) / len(valid_reviews), 1.0)
            progress_bar.progress(progress)

        col3.metric("清掃課題率", f"{(cleaning_count/len(valid_reviews)*100 if valid_reviews else 0):.1f}%")

        # ==========================================
        # 🚀 ここが今回の修正の目玉！エラー回避の鉄壁ガード
        # ==========================================
        # 万が一 results が空っぽでも、見出し（列）だけは作って KeyError を防ぎます
        expected_columns = ["時期", "内容", "清掃関連", "カテゴリ", "ロボット適性", "スコア", "要約"]
        df = pd.DataFrame(results, columns=expected_columns).fillna("-")

        # グラフセクション
        st.subheader("📊 清掃課題の分析結果")
        df_clean = df[df["清掃関連"] == "あり"]
        
        # DataFrameが空じゃない場合のみグラフを描画
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
            st.success("分析した口コミの中に、清掃に関する課題は見当たりませんでした。（またはデータの取得に失敗しました）")

        # 詳細テーブル
        st.subheader("📋 口コミ詳細一覧")
        st.dataframe(df, use_container_width=True)

else:
    st.info("左側のサイドバーからホテル名を入力して「分析を実行」を押してください。")

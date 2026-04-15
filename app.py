import streamlit as st
import googlemaps
from google import genai
from google.genai import types
import json
import pandas as pd
import plotly.express as px

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
    
    with st.spinner("データを収集中..."):
        places_result = gmaps.places(query=target_hotel, language='ja')
        if not places_result['results']:
            st.error("指定されたホテルが見つかりませんでした。")
            st.stop()
            
        place_id = places_result['results'][0]['place_id']
        place_details = gmaps.place(place_id=place_id, fields=['name', 'rating', 'user_ratings_total', 'reviews'], language='ja')
        
        hotel_name = place_details['result'].get('name', '不明')
        total_rating = place_details['result'].get('rating', 0)
        review_count = place_details['result'].get('user_ratings_total', 0)
        reviews = place_details['result'].get('reviews', [])

        if not reviews:
            st.warning("直近の口コミが見つかりませんでした。")
            st.stop()


       # --- （ここより上はそのままです） ---
        
        # ダッシュボード上部のサマリー
        col1, col2, col3 = st.columns(3)
        col1.metric("Google総合評価", f"★{total_rating}")
        col2.metric("総口コミ数", f"{review_count}件")

        # ==========================================
        # 修正箇所：AI分析処理と安全装置
        # ==========================================
        results = []
        cleaning_count = 0
        
        for r in reviews:
            text = r.get('text', '')
            if not text: continue
            
            prompt = f"""
            あなたは清掃ロボット営業マンです。以下の口コミをJSON形式で分析してください。
            1. is_cleaning: (true/false) 清掃関連の不満か
            2. category: 「床のホコリ・ゴミ」「水回りの汚れ・カビ」「ニオイ」「ベッド周辺」「その他清掃」「清掃以外」
            3. robot_match: 清掃ロボットで解決可能か (高/中/低/対象外)
            4. score: 緊急度 (1〜5)
            5. summary: 15文字以内の要約
            口コミ: "{text}"
            """
            
            try:
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash', # ★Colabで成功したモデルに修正
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                analysis = json.loads(response.text)
                if analysis.get('is_cleaning'): cleaning_count += 1
                
                results.append({
                    "時期": r.get('relative_time_description', '-'),
                    "内容": text,
                    "清掃関連": "あり" if analysis.get('is_cleaning') else "なし",
                    "カテゴリ": analysis.get('category', '-'),
                    "ロボット適性": analysis.get('robot_match', '-'),
                    "スコア": analysis.get('score', 0),
                    "要約": analysis.get('summary', '-')
                })
            except Exception as e:
                # ★裏側で何のエラーが起きたか画面に表示する安全装置
                st.error(f"一部の口コミでAI分析エラーが発生しました: {e}")
                continue

        # ★もし全ての分析が失敗して空っぽになった場合のストッパー
        if not results:
            st.error("AIの分析が完了しませんでした。APIの制限などの可能性があります。")
            st.stop()

        col3.metric("清掃課題率(直近)", f"{(cleaning_count/len(reviews)*100):.1f}%")

        # データの表を作成し、英語や空値を日本語化
        df = pd.DataFrame(results).fillna("-")

        # グラフセクション
        st.subheader("📊 清掃課題の分析結果")
        
        # ★安全装置：ちゃんと「清掃関連」列があるか確認してから処理する
        if "清掃関連" in df.columns:
            df_clean = df[df["清掃関連"] == "あり"]
            
            if not df_clean.empty:
                g_col1, g_col2 = st.columns(2)
                
                with g_col1:
                    # 棒グラフの集計データを整理
                    category_counts = df_clean['カテゴリ'].value_counts().reset_index()
                    category_counts.columns = ['カテゴリ', '件数'] # 列名を日本語に指定
                    
                    fig_bar = px.bar(category_counts, 
                                    x='件数', y='カテゴリ', title="課題カテゴリの内訳",
                                    orientation='h') # 横棒グラフに設定
                    fig_bar.update_layout(yaxis={'categoryorder':'total ascending'})
                    st.plotly_chart(fig_bar, use_container_width=True)
                    
                with g_col2:
                    fig_pie = px.pie(df_clean, names='ロボット適性', title="ロボット導入による解決期待度",
                                   color='ロボット適性',
                                   color_discrete_map={'高': '#EF4444', '中': '#F59E0B', '低': '#10B981', '対象外': '#9CA3AF'})
                    st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.success("直近の口コミに清掃に関する課題は見当たりませんでした。")
        else:
             st.warning("分析データが不足しているためグラフを描画できません。")

        # 詳細テーブル
        st.subheader("📋 口コミ詳細一覧")
        st.dataframe(df, use_container_width=True)

else:
    st.info("左側のサイドバーからホテル名を入力して「分析を実行」を押してください。")

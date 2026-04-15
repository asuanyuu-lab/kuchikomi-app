import streamlit as st
import googlemaps
from google import genai
from google.genai import types
import json
import time

# 画面のデザイン
st.set_page_config(page_title="SmartBX 2.0", layout="wide")
st.title("SmartBX 2.0 - オンデマンド口コミ分析 🤖")
st.write("ターゲットホテルの最新口コミを取得し、清掃課題をAIが自動抽出します。")

# 検索ボックスとボタン
target_hotel = st.text_input("分析したいホテル名を入力してください", "Fav 函館")

if st.button("AI分析を実行する", type="primary"):
    if target_hotel:
        # パスワード（Secrets）の読み込み
        MAPS_API_KEY = st.secrets["MAPS_API_KEY"]
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
        
        gmaps = googlemaps.Client(key=MAPS_API_KEY)
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        with st.status("データ収集中...", expanded=True) as status:
            st.write("Googleマップでホテルを検索中...")
            places_result = gmaps.places(query=target_hotel, language='ja')
            
            if not places_result['results']:
                status.update(label="ホテルが見つかりませんでした", state="error")
                st.stop()
                
            place_id = places_result['results'][0]['place_id']
            st.write("口コミを取得中...")
            place_details = gmaps.place(place_id=place_id, fields=['name', 'reviews'], language='ja')
            reviews = place_details.get('result', {}).get('reviews', [])
            
            if not reviews:
                status.update(label="口コミがありません", state="error")
                st.stop()
                
            st.write("Gemini AIで清掃課題を分析中...")
            
            results_list = []
            for review in reviews:
                text = review.get('text', '')
                if not text: continue
                
                prompt = f"""
                あなたは清掃ロボット営業マンです。以下の口コミをJSONで分析してください。
                1. is_cleaning: (true/false)
                2. category: 「床のホコリ・ゴミ」「水回りの汚れ・カビ」「ニオイ」「備品・ベッドの乱れ」「その他清掃」「清掃以外」
                3. robot_match: (高/中/低/対象外)
                4. score: (1〜5の整数)
                5. summary: (15文字以内の要約)
                口コミ: "{text}"
                出力形式: {{"is_cleaning": true, "category": "...", "robot_match": "...", "score": 0, "summary": "..."}}
                """
                
                try:
                    response = ai_client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    analysis = json.loads(response.text)
                    results_list.append({
                        "投稿時期": review.get('relative_time_description', ''),
                        "本文": text,
                        "清掃関連": analysis.get("is_cleaning"),
                        "カテゴリ": analysis.get("category"),
                        "ロボット適性": analysis.get("robot_match"),
                        "スコア": analysis.get("score"),
                        "要約": analysis.get("summary")
                    })
                    time.sleep(2) # 制限対策
                except Exception as e:
                    continue
            
            status.update(label="分析完了！", state="complete")
        
        # 結果を画面に表形式で綺麗に表示
        st.subheader(f"「{target_hotel}」の分析結果")
        st.dataframe(results_list, use_container_width=True)

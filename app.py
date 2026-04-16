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
st.title("🏨 ホテル口コミ分析 - 完全無料版（じゃらん特化型）")

with st.sidebar:
    st.header("設定")
    st.success("✨ 完全無料モード稼働中：\n自動ページめくり＆API制限回避機能搭載！")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索する最大ページ数（※1ページ最大30件）", min_value=1, max_value=30, value=15)
    analyze_btn = st.button("🚀 無料で口コミを抽出＆分析", type="primary")

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
                debug_log.append(f"⚠️ {page+1}ページ目で口コミ要素が見つかりませんでした。抽出を終了します。")
                break 
                
            added_in_this_page = 0
            skipped_in_this_page = 0
            for comment in comments:
                text = comment.get_text(strip=True)
                if len(text) > 10: 
                    if text not in seen_texts:
                        reviews.append({"text": text, "date": "日付不明"})
                        seen_texts.add(text)
                        added_in_this_page += 1
                    else:
                        skipped_in_this_page += 1
            
            debug_log.append(f"→ 新規の口コミを {added_in_this_page}件 取得！ / 重複スキップ: {skipped_in_this_page}件")
            
            if added_in_this_page == 0:
                debug_log.append("⚠️ 新規の口コミが0件のため終了します。")
                break

            next_url = None
            next_link = soup.find('a', class_=re.compile(r'(?i)next'))
            if not next_link:
                next_link = soup.find('a', string=re.compile(r'.*次へ.*'))

            if next_link:
                onclick_attr = next_link.get('onclick', '')
                match = re.search(r"selectPage\('(\d+)','(\d+)'\)", onclick_attr)
                
                if match:
                    next_idx = match.group(1)
                    next_page_num = match.group(2)
                    parsed = urllib.parse.urlparse(current_url)
                    
                    path = re.sub(r'\d+\.html$', '', parsed.path, flags=re.IGNORECASE)
                    if not path.endswith('/'):
                        path += '/'
                    next_path = f"{path}{next_page_num}.HTML"
                    
                    query_params = urllib.parse.parse_qs(parsed.query)
                    query_params['idx'] = [next_idx]
                    if 'screenId' in query_params:
                        query_params['screenId'] = ['UWW3701']
                    new_query = urllib.parse.urlencode(query_params, doseq=True)
                    
                    next_url = urllib.parse.urlunparse((
                        parsed.scheme, parsed.netloc, next_path, 
                        parsed.params, new_query, parsed.fragment
                    ))
                        
            if next_url:
                current_url = next_url
                time.sleep(1) 
            else:
                debug_log.append("「次へ」の遷移処理が見つからないため終了します。")
                break 
                
    except Exception as e:
        debug_log.append(f"🚨 エラー発生: {str(e)}")
        
    return reviews, "\n".join(debug_log)


if analyze_btn:
    if not target_input:
        st.warning("⚠️ じゃらんの口コミURLを入力してください。")
    else:
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        with st.spinner(f"🔍 じゃらんから最大 {max_pages} ページ分のデータを抽出中..."):
            valid_reviews, debug_text = scrape_jalan_reviews(target_input, max_pages)
            actual_count = len(valid_reviews)

        st.success(f"✅ スクレイピング完了！重複を除いた【 実際の口コミ件数：{actual_count}件 】")

        with st.expander("🛠 抽出ログを確認する", expanded=False):
            st.text_area("ログ", debug_text, height=200)

        if actual_count == 0:
            st.error("口コミが取得できませんでした。URLを確認してください。")
            st.stop()

        st.info(f"🤖 AI分析を開始します（処理対象: {actual_count} 件）")
        
        progress_info = st.empty()
        eta_info = st.empty()
        progress_bar = st.progress(0)
        
        results = []
        cleaning_count = 0
        # 修正: 制限回避のためバッチサイズを30件に縮小
        batch_size = 30 
        start_time = time.time()
        
        total_batches = (actual_count + batch_size - 1) // batch_size
        
        for i in range(0, actual_count, batch_size):
            batch_index = (i // batch_size) + 1
            
            elapsed_time = time.time() - start_time
            if i > 0:
                avg_time_per_batch = elapsed_time / (batch_index - 1)
                remaining_batches = total_batches - (batch_index - 1)
                seconds_left = int(avg_time_per_batch * remaining_batches)
                eta_str = str(timedelta(seconds=seconds_left))
            else:
                seconds_left = total_batches * 8 # 目安時間を少し長めに設定
                eta_str = f"計算中... (目安: 約{seconds_left}秒)"

            progress_info.write(f"📊 **分析中:** {min(i + batch_size, actual_count)} / {actual_count} 件目")
            eta_info.write(f"⏳ **完了予測まであと:** `{eta_str}`")
            
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
            
            max_retries = 4
            for attempt in range(max_retries):
                try:
                    # モデルは無料枠で安定しやすい 1.5-flash または 2.0-flash を使用
                    response = ai_client.models.generate_content(
                        model='gemini-2.0-flash',
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
                    
                    # 修正: 成功時もAPI制限にかからないよう3秒休ませる
                    time.sleep(3)
                    break 
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        if attempt < max_retries - 1:
                            # 修正: 429エラーが出たら40秒しっかり待機してリセットを待つ
                            eta_info.write(f"⚠️ API制限を回避中... 40秒待機してから再開します (リトライ {attempt+1}/{max_retries})")
                            time.sleep(40)
                        else: 
                            st.error("APIの制限により中断しました。時間をおいて再度お試しください。")
                            st.stop()
                    else: 
                        st.error(f"予期せぬエラーが発生しました: {e}")
                        st.stop()
            
            progress_bar.progress(min((i + batch_size) / actual_count, 1.0))
            
        progress_info.empty()
        eta_info.empty()
        st.success(f"🎉 分析がすべて完了しました！ (合計 {actual_count} 件)")

        st.divider()

        st.subheader(f"分析結果サマリー")
        col1, col2 = st.columns(2)
        col1.metric("取得した口コミ総数", f"{actual_count}件")
        col2.metric("清掃関連の課題数", f"{cleaning_count}件", delta=f"課題率 {(cleaning_count/actual_count*100 if actual_count > 0 else 0):.1f}%")

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
            st.warning("分析した口コミの中に、清掃に関する課題は見当たりませんでした。")

        st.subheader("📋 口コミ詳細一覧（清掃課題のみ抜粋）")
        st.dataframe(df_clean, use_container_width=True)

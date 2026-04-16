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
st.title("🏨 ホテル口コミ分析 - 完全無料版（じゃらん特化型）")

with st.sidebar:
    st.header("設定")
    st.success("✨ 完全無料モード稼働中：\n自動ページめくり＆重複排除機能搭載！")
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    
    # 修正1: デフォルトを空白に変更
    target_input = st.text_input("じゃらんの口コミURL を入力", "")
    max_pages = st.number_input("探索する最大ページ数（※1ページ最大約30件）", min_value=1, max_value=15, value=5)
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
                debug_log.append("⚠️ 新規の口コミが0件のため、すべての口コミを取得完了したと判定し終了します。")
                break

            # ========================================================
            # 修正2: 404を起こす危険な生成を排除し、的確に「次へ」を探す
            # ========================================================
            next_url = None
            
            # 1. SEO用の <link rel="next"> 
            seo_next = soup.find('link', rel='next')
            if seo_next and seo_next.get('href'):
                next_url = seo_next['href']
            
            # 2. ページネーションエリアをピンポイントで探す（無関係なリンクの誤爆を防ぐ）
            if not next_url:
                pagination_blocks = soup.find_all(['div', 'ul'], class_=re.compile(r'(?i)paging|pagination|jlnpc-kuchikomiPagination'))
                if pagination_blocks:
                    for block in pagination_blocks:
                        for a in block.find_all('a'):
                            text = a.get_text(strip=True)
                            href = a.get('href', '')
                            # 「次」が含まれていて、ダミーリンクではないものを探す
                            if ('次' in text or '>' in text or '＞' in text) and href and not href.startswith(('#', 'javascript')):
                                next_url = href
                                break
                        if next_url:
                            break

            # 3. ページネーションエリアが見つからなかった場合、ページ全体のaタグから慎重に探す
            if not next_url:
                for a in soup.find_all('a'):
                    text = a.get_text(strip=True)
                    href = a.get('href', '')
                    # 「次の宿」などを引かないように「件」や「次へ」に絞る
                    if ('次へ' in text or ('次' in text and '件' in text)) and href and not href.startswith(('#', 'javascript')):
                        next_url = href
                        break

            # 次のURLが見つかった場合の処理
            if next_url:
                if not next_url.startswith('http'):
                    next_url = urllib.parse.urljoin(current_url, next_url)
                
                # ループ検知（ベースURLが同じならストップ）
                current_base = urllib.parse.urldefrag(current_url)[0]
                next_base = urllib.parse.urldefrag(next_url)[0]
                
                if current_base == next_base:
                    debug_log.append("⚠️ 「次へ」のURLがループしているため終了します。")
                    break

                current_url = next_url
                time.sleep(1) 
            else:
                debug_log.append("「次へ」のリンクがないため、最後のページです。")
                break 
                
    except Exception as e:
        debug_log.append(f"🚨 エラー発生: {str(e)}")
        
    return reviews, "\n".join(debug_log)

if analyze_btn:
    if not target_input:
        st.warning("⚠️ じゃらんの口コミURLを入力してください。")
    else:
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        with st.status(f"🔍 じゃらんの口コミを探索中... (最大 {max_pages} ページ)", expanded=True) as status:
            valid_reviews, debug_text = scrape_jalan_reviews(target_input, max_pages)
            actual_count = len(valid_reviews)

            status.update(label=f"✅ スクレイピング完了！重複を除いた【 実際の口コミ件数：{actual_count}件 】", state="complete")

        with st.expander("🛠 【重要】AI分析に回す「生の取得データ」と「ログ」を確認する", expanded=False):
            st.write("※ ここに表示されているテキストが『本当の口コミ』になっているか確認してください。")
            if actual_count > 0:
                st.dataframe(pd.DataFrame(valid_reviews))
            st.text_area("抽出ログ", debug_text, height=150)

        if actual_count == 0:
            st.error("有効な口コミデータが取得できませんでした。上記の抽出ログを確認してください。")
            st.stop()

        with st.spinner(f"🤖 AIが {actual_count} 件の口コミから「清掃課題」を探しています..."):
            results = []
            cleaning_count = 0
            progress_bar = st.progress(0)
            batch_size = 50 
            
            for i in range(0, actual_count, batch_size):
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
                        
                        time.sleep(1) 
                        break 
                    except Exception as e:
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            if attempt < max_retries - 1:
                                time.sleep(10)
                            else: pass 
                        else: break
                
                progress = min((i + batch_size) / actual_count, 1.0)
                progress_bar.progress(progress)
                
        st.success(f"🎉 全 {actual_count} 件の分析が完了しました！")

        st.subheader(f"分析結果（実際の抽出件数: {actual_count}件）")
        col1, col2 = st.columns(2)
        col1.metric("実際に取得した口コミ数", f"{actual_count}件")
        col2.metric("清掃課題率", f"{(cleaning_count/actual_count*100 if actual_count > 0 else 0):.1f}%")

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

        st.subheader("📋 口コミ詳細一覧")
        st.dataframe(df, use_container_width=True)

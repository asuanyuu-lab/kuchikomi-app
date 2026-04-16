import streamlit as st
from google import genai

st.title("📡 Gemini API モデル診断ツール (修正版)")

# サイドバーからキーを読み込み（なければ入力欄を出す）
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_API_KEY = st.sidebar.text_input("API KEYを入力", type="password")

if st.button("利用可能なモデルIDを一覧表示する"):
    if not GEMINI_API_KEY:
        st.error("APIキーが設定されていません。")
    else:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            # シンプルに全モデルを取得
            models = client.models.list()
            
            st.success("接続成功！")
            
            model_data = []
            for m in models:
                # 属性エラーを避けるため、存在する名前と表示名だけを抽出
                model_data.append({
                    "正確なID (これをコピー)": m.name,
                    "モデル表示名": m.display_name
                })
            
            if model_data:
                st.table(model_data)
                st.info("この表の中にある『正確なID』を教えてください。そのIDをコードに固定します。")
            else:
                st.warning("利用可能なモデルが1つも見つかりませんでした。")
                
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
            st.info("APIキーが正しいか、Google AI Studioでお支払い設定が完了しているか再確認してください。")

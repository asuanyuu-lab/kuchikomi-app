import streamlit as st
from google import genai

st.title("📡 Gemini API モデル診断ツール")
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

if st.button("利用可能なモデルIDを一覧表示する"):
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        models = client.models.list()
        
        st.success("接続成功！あなたのAPIキーで利用可能なモデルIDは以下の通りです：")
        
        model_data = []
        for m in models:
            # generateContentをサポートしているモデルだけを抽出
            if 'generateContent' in m.supported_methods:
                model_data.append({
                    "モデル名": m.display_name,
                    "正確なID": m.name # これがコードに書くべき名前
                })
        
        st.table(model_data)
        st.info("↑ この表にある『正確なID』のいずれかをコピーして、次のコードに貼り付けます。")
        
    except Exception as e:
        st.error(f"接続エラーが発生しました。APIキーを確認してください: {e}")

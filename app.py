import streamlit as st
import pandas as pd

st.set_page_config(page_title="Aifuge Quote System", layout="wide")

st.title("🚛 Aifuge 双承运商报价系统（生产版）")

# ===== 侧边参数 =====
st.sidebar.header("⚙ 参数")

dhl_fuel = st.sidebar.number_input("DHL Fuel %", value=0.12)
raben_daf = st.sidebar.number_input("Raben DAF %", value=0.10)

# ===== 输入区 =====
st.header("📦 输入")

col1, col2, col3 = st.columns(3)

with col1:
    scope = st.selectbox("Scope", ["DE", "EU"])
    country = st.text_input("Destination Country", value="Deutschland")

with col2:
    weight = st.number_input("Actual Weight (kg)", value=200.0)

with col3:
    plz = st.text_input("Destination PLZ (前2位)", value="38")

if st.button("💰 计算报价"):

    try:
        # ===== 读取数据 =====
        raben_zone = pd.read_csv("data/raben_zone_map.csv")
        raben_rates = pd.read_csv("data/raben_rates_long.csv")
        dhl_zone = pd.read_csv("data/dhl_de_plz2_zone.csv")
        dhl_rates = pd.read_csv("data/dhl_de_rates.csv")

        # ==============================
        # RABEN
        # ==============================

        rz = raben_zone[
            (raben_zone["scope"] == scope) &
            (raben_zone["country"] == country) &
            (raben_zone["plz"].astype(str) == plz)
        ]

        if rz.empty:
            st.error("Raben: 无法匹配分区")
        else:
            zone = rz.iloc[0]["zone"]

            rr = raben_rates[
                (raben_rates["scope"] == scope) &
                (raben_rates["country"] == country) &
                (raben_rates["zone"] == zone) &
                (raben_rates["w_from"] <= weight) &
                (raben_rates["w_to"] > weight)
            ]

            if rr.empty:
                st.error("Raben: 无法匹配重量段")
            else:
                base_price = rr.iloc[0]["price"]
                total = base_price * (1 + raben_daf)

                st.success(f"Raben 价格: {round(total,2)} €")

        # ==============================
        # DHL (只处理 DE)
        # ==============================

        if scope == "DE":

            dz = dhl_zone[dhl_zone["plz"].astype(str) == plz]

            if dz.empty:
                st.error("DHL: 无法匹配分区")
            else:
                zone = dz.iloc[0]["zone"]

                dr = dhl_rates[
                    (dhl_rates["zone"] == zone) &
                    (dhl_rates["w_from"] <= weight) &
                    (dhl_rates["w_to"] > weight)
                ]

                if dr.empty:
                    st.error("DHL: 无法匹配重量段")
                else:
                    base_price = dr.iloc[0]["price"]
                    total = base_price * (1 + dhl_fuel)

                    st.success(f"DHL 价格: {round(total,2)} €")

    except Exception as e:
        st.error(f"系统错误: {e}")

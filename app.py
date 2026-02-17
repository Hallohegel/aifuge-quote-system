import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="Aifuge Quote System", layout="wide")

# -----------------------------
# 加载数据
# -----------------------------
DATA_PATH = "data"

def load_csv(filename):
    return pd.read_csv(os.path.join(DATA_PATH, filename))

dhl_de_zone = load_csv("dhl_de_plz2_zone.csv")
dhl_de_rates = load_csv("dhl_de_rates.csv")
dhl_eu_zone = load_csv("dhl_eu_zone_map.csv")
dhl_eu_rates = load_csv("dhl_eu_rates_long.csv")
raben_zone = load_csv("raben_zone_map.csv")
raben_rates = load_csv("raben_rates_long.csv")
raben_diesel = load_csv("raben_diesel_floater.csv")

# -----------------------------
# 标题
# -----------------------------
st.title("🚛 Aifuge 双承运商报价系统（生产版）")

# -----------------------------
# 侧边栏参数
# -----------------------------
st.sidebar.header("⚙ 参数")

dhl_fuel = st.sidebar.number_input("DHL Fuel %", value=0.12)
dhl_security = st.sidebar.number_input("DHL Sicherheitszuschlag %", value=0.00)

raben_daf = st.sidebar.number_input("Raben DAF %", value=0.10)
raben_mob = st.sidebar.number_input("Raben Mobilitäts-Floater %", value=0.029)
raben_adr_fee = st.sidebar.number_input("Raben ADR Fee €", value=12.5)
raben_avis_fee = st.sidebar.number_input("Raben Avis Fee €", value=12.0)
raben_ins_min = st.sidebar.number_input("Raben Insurance Min €", value=5.95)

# -----------------------------
# 输入区
# -----------------------------
st.header("📦 输入")

col1, col2, col3 = st.columns(3)

with col1:
    scope = st.selectbox("Scope (DE/EU)", ["DE", "EU"])

with col2:
    weight = st.number_input("Actual Weight (kg)", value=200.0)

with col3:
    packaging = st.selectbox("Packaging Type", ["Europalette"])

if scope == "DE":
    dest_plz = st.text_input("Destination PLZ (前2位)", value="38")[:2]
    dest_country = "DE"
else:
    dest_country = st.selectbox("Destination Country", dhl_eu_zone["country_code"].unique())
    dest_plz = st.text_input("Destination PLZ (前2位)", value="44")[:2]

adr = st.checkbox("ADR (危险品)")
avis = st.checkbox("Avis 预约派送")
insurance_value = st.number_input("Insurance Value €", value=0.0)

# -----------------------------
# 计算按钮
# -----------------------------
if st.button("💰 计算报价"):

    st.header("📊 结果（Netto）")

    # =========================
    # DHL 计算
    # =========================
    try:
        if scope == "DE":
            zone_row = dhl_de_zone[dhl_de_zone["plz2"] == int(dest_plz)]
            zone = zone_row.iloc[0]["zone"]
            rate_row = dhl_de_rates[
                (dhl_de_rates["zone"] == zone) &
                (dhl_de_rates["weight_from"] <= weight) &
                (dhl_de_rates["weight_to"] >= weight)
            ]
        else:
            zone_row = dhl_eu_zone[
                (dhl_eu_zone["country_code"] == dest_country) &
                (dhl_eu_zone["plz2"] == int(dest_plz))
            ]
            zone = zone_row.iloc[0]["zone"]
            rate_row = dhl_eu_rates[
                (dhl_eu_rates["zone"] == zone) &
                (dhl_eu_rates["weight_from"] <= weight) &
                (dhl_eu_rates["weight_to"] >= weight)
            ]

        base = rate_row.iloc[0]["rate"]
        total = base * (1 + dhl_fuel + dhl_security)

        st.subheader("DHL Freight")
        st.success(f"€ {round(total,2)}")

    except:
        st.subheader("DHL Freight")
        st.error("DHL：无法匹配分区或重量段")

    # =========================
    # Raben 计算
    # =========================
    try:
        zone_row = raben_zone[
            (raben_zone["country_code"] == dest_country) &
            (raben_zone["plz2"] == int(dest_plz))
        ]
        zone = zone_row.iloc[0]["zone"]

        rate_row = raben_rates[
            (raben_rates["zone"] == zone) &
            (raben_rates["weight_from"] <= weight) &
            (raben_rates["weight_to"] >= weight)
        ]

        base = rate_row.iloc[0]["rate"]

        total = base * (1 + raben_daf + raben_mob)

        if adr:
            total += raben_adr_fee

        if avis:
            total += raben_avis_fee

        if insurance_value > 0:
            insurance = max(insurance_value * 0.003, raben_ins_min)
            total += insurance

        st.subheader("Raben")
        st.success(f"€ {round(total,2)}")

    except:
        st.subheader("Raben")
        st.error("Raben：无法匹配分区或重量段")

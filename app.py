import streamlit as st
import pandas as pd

st.set_page_config(page_title="Aifuge Freight Quote Engine", layout="wide")

st.title("🚛 Aifuge 双承运商报价系统")

# 示例数据（后续可替换为真实数据）
dhl_data = pd.DataFrame({
    "zone": [1,1,2,2],
    "weight_max": [200,500,200,500],
    "price": [120,180,150,220]
})

raben_data = pd.DataFrame({
    "zone": [1,1,2,2],
    "weight_max": [200,500,200,500],
    "price": [110,170,140,210]
})

col1, col2 = st.columns(2)

with col1:
    zone = st.number_input("Zone", min_value=1, max_value=20, value=1)
    weight = st.number_input("重量 (kg)", min_value=1.0, value=200.0)

with col2:
    fuel_pct = st.number_input("DHL Fuel %", value=12.0) / 100
    daf_pct = st.number_input("Raben DAF %", value=10.0) / 100

def calc_dhl(weight, zone):
    row = dhl_data[(dhl_data["zone"]==zone) & (dhl_data["weight_max"]>=weight)].iloc[0]
    base = row["price"]
    fuel = base * fuel_pct
    return base + fuel

def calc_raben(weight, zone):
    row = raben_data[(raben_data["zone"]==zone) & (raben_data["weight_max"]>=weight)].iloc[0]
    base = row["price"]
    daf = base * daf_pct
    return base + daf

if st.button("计算报价"):
    dhl_price = calc_dhl(weight, zone)
    raben_price = calc_raben(weight, zone)

    st.subheader("报价结果")

    col1, col2 = st.columns(2)

    with col1:
        st.metric("DHL 报价 (€)", f"{dhl_price:.2f}")

    with col2:
        st.metric("Raben 报价 (€)", f"{raben_price:.2f}")

    if dhl_price < raben_price:
        st.success("推荐承运商：DHL")
    else:
        st.success("推荐承运商：Raben")

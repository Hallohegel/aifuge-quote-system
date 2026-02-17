import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st


DATA_DIR = Path("data")

# ----------------------------
# Helpers
# ----------------------------
def load_csv(name: str) -> pd.DataFrame:
    p = DATA_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"Missing file: {p}")
    return pd.read_csv(p)

def load_params_default() -> dict:
    p = DATA_DIR / "params_default.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def norm_plz2(x: str) -> str:
    s = str(x or "").strip()
    s = re.sub(r"\D", "", s)  # keep digits
    if len(s) >= 2:
        return s[:2]
    return s.zfill(2) if s else ""

def norm_country_code(x: str) -> str:
    """
    Accept: 'PL', 'Polen', 'Poland', 'Deutschland', 'Germany', etc.
    Return: ISO2 like 'PL', 'DE', ...
    """
    s = str(x or "").strip()
    if not s:
        return ""

    # If user directly inputs ISO2
    if re.fullmatch(r"[A-Za-z]{2}", s):
        return s.upper()

    key = s.lower().strip()

    mapping = {
        # DE
        "deutschland": "DE", "germany": "DE", "de": "DE",
        # PL
        "polen": "PL", "poland": "PL", "pl": "PL",
        # BG
        "bulgarien": "BG", "bulgaria": "BG", "bg": "BG",
        # LV
        "lettland": "LV", "latvia": "LV", "lv": "LV",
        # NL
        "niederlande": "NL", "netherlands": "NL", "holland": "NL", "nl": "NL",
        # FR
        "frankreich": "FR", "france": "FR", "fr": "FR",
        # IT
        "italien": "IT", "italy": "IT", "it": "IT",
        # ES
        "spanien": "ES", "spain": "ES", "es": "ES",
        # add more if you want
    }

    return mapping.get(key, "")

def pick_rate(rates_df: pd.DataFrame, weight: float):
    """
    rates_df columns: w_from, w_to, price
    Pick first row where w_from < weight <= w_to (or weight==0 => first bracket)
    """
    if rates_df.empty:
        return None

    w = float(weight)

    # tolerate 0 weight => treat as smallest bracket
    if w <= 0:
        row = rates_df.sort_values(["w_to"]).iloc[0]
        return row

    df = rates_df.copy()
    df["w_from"] = df["w_from"].astype(float)
    df["w_to"] = df["w_to"].astype(float)

    hit = df[(df["w_from"] < w) & (w <= df["w_to"])].sort_values(["w_to"])
    if not hit.empty:
        return hit.iloc[0]

    # If not found, maybe user weight exceeds max
    max_to = float(df["w_to"].max())
    return {"_exceed": True, "max_to": max_to}

# ----------------------------
# Load data
# ----------------------------
@st.cache_data
def load_all_data():
    dhl_de_plz2_zone = load_csv("dhl_de_plz2_zone.csv")           # plz2, zone
    dhl_de_rates = load_csv("dhl_de_rates.csv")                   # zone, w_from, w_to, price
    dhl_eu_zone_map = load_csv("dhl_eu_zone_map.csv")             # country_code, plz, zone
    dhl_eu_rates_long = load_csv("dhl_eu_rates_long.csv")         # country_code, zone, w_from, w_to, price

    raben_zone_map = None
    raben_rates_long = None
    if (DATA_DIR / "raben_zone_map.csv").exists():
        raben_zone_map = load_csv("raben_zone_map.csv")           # scope,country,plz,zone
    if (DATA_DIR / "raben_rates_long.csv").exists():
        raben_rates_long = load_csv("raben_rates_long.csv")       # scope,country,zone,w_from,w_to,price

    return {
        "dhl_de_plz2_zone": dhl_de_plz2_zone,
        "dhl_de_rates": dhl_de_rates,
        "dhl_eu_zone_map": dhl_eu_zone_map,
        "dhl_eu_rates_long": dhl_eu_rates_long,
        "raben_zone_map": raben_zone_map,
        "raben_rates_long": raben_rates_long,
    }

data = load_all_data()
params_default = load_params_default()

# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="Aifuge 双承运商报价系统（生产版）", layout="wide")
st.title("🚚 Aifuge 双承运商报价系统（生产版）")

# Sidebar params
st.sidebar.header("⚙️ 参数")
dhl_fuel = st.sidebar.number_input(
    "DHL Fuel %", min_value=0.0, max_value=1.0,
    value=float(params_default.get("dhl_fuel", 0.12)),
    step=0.01, format="%.2f",
)
dhl_security = st.sidebar.number_input(
    "DHL Sicherheitszuschlag %", min_value=0.0, max_value=1.0,
    value=float(params_default.get("dhl_security", 0.00)),
    step=0.01, format="%.2f",
)

raben_daf = st.sidebar.number_input(
    "Raben DAF %", min_value=0.0, max_value=1.0,
    value=float(params_default.get("raben_daf", 0.10)),
    step=0.01, format="%.2f",
)

# Inputs
st.subheader("📦 输入")
col1, col2, col3 = st.columns([2, 2, 2])

with col1:
    scope = st.selectbox("Scope", ["DE", "EU"], index=0)
    dest_country_raw = st.text_input("Destination Country（可输入：Polen/PL/波兰 等）", value="Deutschland")
with col2:
    weight = st.number_input("Actual Weight (kg)", min_value=0.0, value=200.0, step=10.0, format="%.2f")
with col3:
    dest_plz2_raw = st.text_input("Destination PLZ (前2位)", value="38")

dest_plz2 = norm_plz2(dest_plz2_raw)
dest_cc = norm_country_code(dest_country_raw)

btn = st.button("💰 计算报价")

# ----------------------------
# Calculation
# ----------------------------
st.divider()
st.subheader("📊 结果（Netto）")

res_col1, res_col2 = st.columns(2)

if btn:
    # --- DHL ---
    try:
        if scope == "DE":
            # map zone by plz2
            zmap = data["dhl_de_plz2_zone"].copy()
            zmap["plz2"] = zmap["plz2"].astype(str).str.zfill(2)

            hit = zmap[zmap["plz2"] == dest_plz2]
            if hit.empty:
                dhl_msg = f"DHL：无法匹配 DE PLZ2={dest_plz2}（检查 dhl_de_plz2_zone.csv）"
            else:
                zone = int(hit.iloc[0]["zone"])
                rates = data["dhl_de_rates"]
                rates_zone = rates[rates["zone"] == zone]
                picked = pick_rate(rates_zone, weight)

                if isinstance(picked, dict) and picked.get("_exceed"):
                    dhl_msg = f"DHL：重量 {weight:.2f}kg 超出 DE 价目最大 {picked['max_to']:.0f}kg（需要补全表或走特殊报价）"
                else:
                    base = float(picked["price"])
                    fuel_fee = base * float(dhl_fuel)
                    sec_fee = base * float(dhl_security)
                    total = base + fuel_fee + sec_fee

                    dhl_msg = f"Zone {zone} | Base €{base:.2f} | Fuel {dhl_fuel*100:.2f}% | Security {dhl_security*100:.2f}% | Total €{total:.2f}"

        else:
            # EU export: need country_code + plz2
            if not dest_cc:
                dhl_msg = f"DHL：EU 需要国家代码（例如 PL / BG / LV）。你输入的是：{dest_country_raw}"
            else:
                zmap = data["dhl_eu_zone_map"].copy()
                zmap["country_code"] = zmap["country_code"].astype(str).str.upper()
                zmap["plz"] = zmap["plz"].astype(str).str.zfill(2)

                hit = zmap[(zmap["country_code"] == dest_cc) & (zmap["plz"] == dest_plz2)]
                if hit.empty:
                    dhl_msg = f"DHL：无法匹配 EU {dest_cc}-{dest_plz2}（检查 dhl_eu_zone_map.csv）"
                else:
                    zone = int(hit.iloc[0]["zone"])
                    rates = data["dhl_eu_rates_long"].copy()
                    rates["country_code"] = rates["country_code"].astype(str).str.upper()
                    rates_zone = rates[(rates["country_code"] == dest_cc) & (rates["zone"] == zone)]
                    picked = pick_rate(rates_zone, weight)

                    if isinstance(picked, dict) and picked.get("_exceed"):
                        dhl_msg = f"DHL：重量 {weight:.2f}kg 超出 EU 价目最大 {picked['max_to']:.0f}kg（DHL Export 表通常到 2500kg）"
                    else:
                        base = float(picked["price"])
                        fuel_fee = base * float(dhl_fuel)
                        sec_fee = base * float(dhl_security)
                        total = base + fuel_fee + sec_fee
                        dhl_msg = f"{dest_cc}-{dest_plz2} Zone {zone} | Base €{base:.2f} | Fuel {dhl_fuel*100:.2f}% | Security {dhl_security*100:.2f}% | Total €{total:.2f}"

    except Exception as e:
        dhl_msg = f"DHL 系统错误：{e}"

    # --- Raben ---
    try:
        rz = data["raben_zone_map"]
        rr = data["raben_rates_long"]
        if rz is None or rr is None:
            raben_msg = "Raben：未检测到 raben_zone_map.csv / raben_rates_long.csv"
        else:
            # Raben uses (scope,country,plz,zone)
            rz2 = rz.copy()
            rz2["plz"] = rz2["plz"].astype(str).str.zfill(2)
            rz2["scope"] = rz2["scope"].astype(str).str.upper()

            # country is free text in your file (e.g. Polen, Deutschland...)
            # we keep user's raw input to match; you can standardize later
            hit = rz2[(rz2["scope"] == scope) & (rz2["country"] == dest_country_raw) & (rz2["plz"] == dest_plz2)]
            if hit.empty:
                raben_msg = f"Raben：无法匹配 {scope} {dest_country_raw}-{dest_plz2}（检查 raben_zone_map.csv）"
            else:
                zone = int(hit.iloc[0]["zone"])
                rr2 = rr.copy()
                rr2["scope"] = rr2["scope"].astype(str).str.upper()
                rates_zone = rr2[(rr2["scope"] == scope) & (rr2["country"] == dest_country_raw) & (rr2["zone"] == zone)]
                picked = pick_rate(rates_zone, weight)

                if isinstance(picked, dict) and picked.get("_exceed"):
                    raben_msg = f"Raben：重量 {weight:.2f}kg 超出价目最大 {picked['max_to']:.0f}kg（需要补全到 5000kg）"
                else:
                    base = float(picked["price"])
                    daf_fee = base * float(raben_daf)
                    total = base + daf_fee
                    raben_msg = f"{dest_country_raw} Zone {zone} | Base €{base:.2f} | DAF {raben_daf*100:.2f}% | Total €{total:.2f}"

    except Exception as e:
        raben_msg = f"Raben 系统错误：{e}"

    with res_col1:
        st.markdown("### DHL Freight")
        if "错误" in dhl_msg or "无法匹配" in dhl_msg or "超出" in dhl_msg:
            st.error(dhl_msg)
        else:
            st.success(dhl_msg)

    with res_col2:
        st.markdown("### Raben")
        if "错误" in raben_msg or "无法匹配" in raben_msg or "超出" in raben_msg or "未检测到" in raben_msg:
            st.error(raben_msg)
        else:
            st.success(raben_msg)

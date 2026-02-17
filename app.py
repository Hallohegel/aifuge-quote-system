import os
import json
import pandas as pd
import streamlit as st

# =========================
# Helpers
# =========================
DATA_DIR = "data"

def p(path: str) -> str:
    return os.path.join(DATA_DIR, path)

def load_csv(path: str) -> pd.DataFrame:
    full = p(path)
    if not os.path.exists(full):
        raise FileNotFoundError(f"找不到文件：{full}")
    df = pd.read_csv(full)
    # Normalize column names (strip spaces)
    df.columns = [c.strip() for c in df.columns]
    return df

def must_have_cols(df: pd.DataFrame, cols: list[str], name: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"{name} 缺少列：{missing}，当前列：{list(df.columns)}")

def norm_str(x: str) -> str:
    return (x or "").strip()

def norm_upper(x: str) -> str:
    return norm_str(x).upper()

def to_int_safe(x: str):
    x = norm_str(x)
    if x == "":
        return None
    try:
        return int(x)
    except:
        return None

def find_bracket(rates: pd.DataFrame, weight: float) -> pd.Series | None:
    """
    rates must contain w_from, w_to.
    Bracket rule:
    - for w_from==0: [0, w_to]
    - otherwise: (w_from, w_to]
    """
    r = rates.copy()
    r["w_from"] = pd.to_numeric(r["w_from"], errors="coerce")
    r["w_to"] = pd.to_numeric(r["w_to"], errors="coerce")
    r = r.dropna(subset=["w_from", "w_to"]).sort_values(["w_from", "w_to"], ascending=[True, True])

    for _, row in r.iterrows():
        w_from = float(row["w_from"])
        w_to = float(row["w_to"])
        if w_from == 0 and weight >= 0 and weight <= w_to:
            return row
        if weight > w_from and weight <= w_to:
            return row
    return None

def euro(x: float) -> str:
    return f"€{x:,.2f}"

# Country alias mapping (you can expand later)
COUNTRY_ALIASES_TO_RABEN_NAME = {
    # Poland
    "PL": "Polen",
    "POLAND": "Polen",
    "POLEN": "Polen",
    "波兰": "Polen",
    # Germany
    "DE": "Deutschland",
    "GERMANY": "Deutschland",
    "DEUTSCHLAND": "Deutschland",
    "德国": "Deutschland",
    # Bulgaria
    "BG": "Bulgarien",
    "BULGARIA": "Bulgarien",
    "BULGARIEN": "Bulgarien",
    "保加利亚": "Bulgarien",
    # Latvia
    "LV": "Lettland",
    "LATVIA": "Lettland",
    "LETTLAND": "Lettland",
    "拉脱维亚": "Lettland",
}

COUNTRY_ALIASES_TO_CODE = {
    "PL": "PL", "POLAND": "PL", "POLEN": "PL", "波兰": "PL",
    "DE": "DE", "GERMANY": "DE", "DEUTSCHLAND": "DE", "德国": "DE",
    "BG": "BG", "BULGARIA": "BG", "BULGARIEN": "BG", "保加利亚": "BG",
    "LV": "LV", "LATVIA": "LV", "LETTLAND": "LV", "拉脱维亚": "LV",
}

def map_to_raben_country_name(user_input: str) -> str:
    k = norm_upper(user_input)
    return COUNTRY_ALIASES_TO_RABEN_NAME.get(k, norm_str(user_input))

def map_to_country_code(user_input: str) -> str:
    k = norm_upper(user_input)
    return COUNTRY_ALIASES_TO_CODE.get(k, k if len(k) == 2 else norm_str(user_input))


# =========================
# UI
# =========================
st.set_page_config(page_title="Aifuge 双承运商报价系统（生产版）", layout="wide")
st.title("🚚 Aifuge 双承运商报价系统（生产版）")

# Load defaults (optional)
defaults = {}
try:
    with open(p("params_default.json"), "r", encoding="utf-8") as f:
        defaults = json.load(f)
except:
    defaults = {}

# Sidebar params
st.sidebar.header("⚙️ 参数")
dhl_fuel = st.sidebar.number_input("DHL Fuel %", value=float(defaults.get("dhl_fuel", 0.12)), step=0.01, format="%.2f")
dhl_security = st.sidebar.number_input("DHL Sicherheitszuschlag %", value=float(defaults.get("dhl_security", 0.00)), step=0.01, format="%.2f")

raben_daf = st.sidebar.number_input("Raben DAF %", value=float(defaults.get("raben_daf", 0.10)), step=0.01, format="%.2f")

# Inputs
st.subheader("📦 输入")

c1, c2, c3 = st.columns([2, 2, 2])

with c1:
    scope = st.selectbox("Scope", ["DE", "EU"], index=0)
    dest_country_raw = st.text_input("Destination Country（可输入：Polen/PL/波兰 等）", value="Deutschland")

with c2:
    weight = st.number_input("Actual Weight (kg)", min_value=0.0, value=200.0, step=10.0, format="%.2f")

with c3:
    plz2_str = st.text_input("Destination PLZ (前2位)", value="38")

btn = st.button("💰 计算报价")

st.divider()
st.subheader("📊 结果（Netto）")

left, right = st.columns(2)

# =========================
# Calculate
# =========================
def calc_dhl(scope: str, dest_country_raw: str, plz2: int, weight: float) -> tuple[bool, str]:
    """
    Returns (ok, message)
    """
    try:
        if scope == "DE":
            # zone mapping by plz2
            df_zone = load_csv("dhl_de_plz2_zone.csv")
            must_have_cols(df_zone, ["plz2", "zone"], "dhl_de_plz2_zone.csv")
            df_zone["plz2"] = pd.to_numeric(df_zone["plz2"], errors="coerce").astype("Int64")
            zrow = df_zone[df_zone["plz2"] == plz2]
            if zrow.empty:
                return (False, f"DHL: 找不到 DE 的 PLZ2={plz2} 对应 Zone（检查 dhl_de_plz2_zone.csv）")
            zone = int(zrow.iloc[0]["zone"])

            # rates
            df_rates = load_csv("dhl_de_rates.csv")
            must_have_cols(df_rates, ["zone", "w_from", "w_to", "price"], "dhl_de_rates.csv")
            df_rates["zone"] = pd.to_numeric(df_rates["zone"], errors="coerce").astype("Int64")
            r = df_rates[df_rates["zone"] == zone]
            if r.empty:
                return (False, f"DHL: 找不到 Zone={zone} 的报价（检查 dhl_de_rates.csv）")

            row = find_bracket(r, weight)
            if row is None:
                return (False, f"DHL: 无法匹配重量段（当前 {weight}kg）。请确认 dhl_de_rates.csv 覆盖到至少 2500kg")

            base = float(row["price"])
            total = base * (1.0 + float(dhl_fuel) + float(dhl_security))
            msg = f"DE PLZ2={plz2} | Zone {zone} | Base {euro(base)} | Fuel {dhl_fuel*100:.2f}% | Security {dhl_security*100:.2f}% | Total {euro(total)}"
            return (True, msg)

        # scope == EU : use country_code + plz2 => zone
        country_code = map_to_country_code(dest_country_raw)
        if len(country_code) != 2:
            return (False, "DHL EU: 请输入国家二字码（如 PL/BG/LV），或输入 Poland/Polen/波兰 也可以")

        df_zone = load_csv("dhl_eu_zone_map.csv")
        must_have_cols(df_zone, ["country_code", "plz2", "zone"], "dhl_eu_zone_map.csv")
        df_zone["country_code"] = df_zone["country_code"].astype(str).str.upper().str.strip()
        df_zone["plz2"] = pd.to_numeric(df_zone["plz2"], errors="coerce").astype("Int64")

        zrow = df_zone[(df_zone["country_code"] == country_code) & (df_zone["plz2"] == plz2)]
        if zrow.empty:
            return (False, f"DHL EU: 找不到 {country_code} + PLZ2={plz2} 的 Zone（检查 dhl_eu_zone_map.csv）")
        zone = int(zrow.iloc[0]["zone"])

        df_rates = load_csv("dhl_eu_rates_long.csv")
        must_have_cols(df_rates, ["country_code", "zone", "w_from", "w_to", "price"], "dhl_eu_rates_long.csv")
        df_rates["country_code"] = df_rates["country_code"].astype(str).str.upper().str.strip()
        df_rates["zone"] = pd.to_numeric(df_rates["zone"], errors="coerce").astype("Int64")

        r = df_rates[(df_rates["country_code"] == country_code) & (df_rates["zone"] == zone)]
        if r.empty:
            return (False, f"DHL EU: 找不到 {country_code} Zone={zone} 的报价（检查 dhl_eu_rates_long.csv）")

        row = find_bracket(r, weight)
        if row is None:
            return (False, f"DHL EU: 无法匹配重量段（当前 {weight}kg）。请确认 EU 表覆盖到至少 2500kg")

        base = float(row["price"])
        total = base * (1.0 + float(dhl_fuel) + float(dhl_security))
        msg = f"{country_code}-{plz2} | Zone {zone} | Base {euro(base)} | Fuel {dhl_fuel*100:.2f}% | Security {dhl_security*100:.2f}% | Total {euro(total)}"
        return (True, msg)

    except Exception as e:
        return (False, f"DHL 系统错误：{e}")

def calc_raben(scope: str, dest_country_raw: str, plz2: int, weight: float) -> tuple[bool, str]:
    """
    Returns (ok, message)
    """
    try:
        raben_country = map_to_raben_country_name(dest_country_raw)

        df_zone = load_csv("raben_zone_map.csv")
        must_have_cols(df_zone, ["scope", "country", "plz2", "zone"], "raben_zone_map.csv")
        df_zone["scope"] = df_zone["scope"].astype(str).str.upper().str.strip()
        df_zone["country"] = df_zone["country"].astype(str).str.strip()
        df_zone["plz2"] = pd.to_numeric(df_zone["plz2"], errors="coerce").astype("Int64")

        zrow = df_zone[(df_zone["scope"] == scope) & (df_zone["country"] == raben_country) & (df_zone["plz2"] == plz2)]
        if zrow.empty:
            return (False, f"Raben: 找不到 {scope} / {raben_country} / PLZ2={plz2} 的 Zone（检查 raben_zone_map.csv）")
        zone = int(zrow.iloc[0]["zone"])

        df_rates = load_csv("raben_rates_long.csv")
        must_have_cols(df_rates, ["scope", "country", "zone", "w_from", "w_to", "price"], "raben_rates_long.csv")
        df_rates["scope"] = df_rates["scope"].astype(str).str.upper().str.strip()
        df_rates["country"] = df_rates["country"].astype(str).str.strip()
        df_rates["zone"] = pd.to_numeric(df_rates["zone"], errors="coerce").astype("Int64")

        r = df_rates[(df_rates["scope"] == scope) & (df_rates["country"] == raben_country) & (df_rates["zone"] == zone)]
        if r.empty:
            return (False, f"Raben: 找不到 {scope}/{raben_country} Zone={zone} 的报价（检查 raben_rates_long.csv）")

        row = find_bracket(r, weight)
        if row is None:
            return (False, f"Raben: 无法匹配重量段（当前 {weight}kg）。请确认 Raben 表覆盖到至少 5000kg，并且 w_from/w_to 正确")

        base = float(row["price"])
        total = base * (1.0 + float(raben_daf))
        msg = f"{raben_country} Zone {zone} | Base {euro(base)} | DAF {raben_daf*100:.2f}% | Total {euro(total)}"
        return (True, msg)

    except Exception as e:
        return (False, f"Raben 系统错误：{e}")

# Run on button
if btn:
    plz2 = to_int_safe(plz2_str)
    if plz2 is None:
        left.error("请在 PLZ (前2位) 输入数字，比如 38 / 44")
        right.error("请在 PLZ (前2位) 输入数字，比如 38 / 44")
    else:
        ok_dhl, msg_dhl = calc_dhl(scope, dest_country_raw, plz2, float(weight))
        ok_raben, msg_raben = calc_raben(scope, dest_country_raw, plz2, float(weight))

        with left:
            st.markdown("### DHL Freight")
            if ok_dhl:
                st.success(msg_dhl)
            else:
                st.error(msg_dhl)

        with right:
            st.markdown("### Raben")
            if ok_raben:
                st.success(msg_raben)
            else:
                st.error(msg_raben)

else:
    with left:
        st.markdown("### DHL Freight")
        st.info("请填写参数后点击「计算报价」")
    with right:
        st.markdown("### Raben")
        st.info("请填写参数后点击「计算报价」")

import streamlit as st
import pandas as pd
import io
import os
import re

st.set_page_config(page_title="Aifuge 双承运商报价系统（生产版）", layout="wide")

DATA_DIR = "data"

# -----------------------------
# Utils
# -----------------------------
def norm_plz2(x) -> str:
    """
    Accept: '38', 38, '38110', '044', etc -> '38' / '04'
    Rule: take first 2 digits from a string of digits.
    """
    if x is None:
        return ""
    s = str(x).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 2:
        return digits[:2].zfill(2)
    if len(digits) == 1:
        return digits.zfill(2)
    return ""

def norm_country_code(x) -> str:
    return str(x).strip().upper()

def norm_country_name(x) -> str:
    return str(x).strip().lower()

def safe_float(x, default=None):
    try:
        if x is None:
            return default
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return default

def read_csv_flexible(path: str) -> pd.DataFrame:
    """
    Fix common issues:
    - file is TSV but read_csv default sep=',' -> ends up as single column
    - weird BOM
    - headers contain tabs or semicolons
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在：{path}")

    raw = open(path, "rb").read()
    text = raw.decode("utf-8-sig", errors="ignore")

    # Heuristic delimiter detection from header line
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if ("\t" in first_line) and ("," not in first_line):
        sep = "\t"
    elif (";" in first_line) and ("," not in first_line):
        sep = ";"
    else:
        sep = ","  # default

    df = pd.read_csv(io.StringIO(text), sep=sep, engine="python")

    # If still single column and it looks like it contains separators -> split
    if df.shape[1] == 1:
        col0 = df.columns[0]
        if "\t" in col0:
            # header got swallowed into single column name
            parts = col0.split("\t")
            df = pd.read_csv(io.StringIO(text), sep="\t", engine="python")
        elif ";" in col0:
            df = pd.read_csv(io.StringIO(text), sep=";", engine="python")
        elif "," in col0:
            df = pd.read_csv(io.StringIO(text), sep=",", engine="python")

    # Strip column names
    df.columns = [str(c).strip() for c in df.columns]
    return df

def pick_weight_band(df: pd.DataFrame, weight: float):
    """
    Expect df has w_from, w_to, price
    Returns row (Series) or None
    """
    if df is None or df.empty:
        return None

    # Coerce
    for c in ["w_from", "w_to", "price"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # If w_to missing for last band, treat as +inf
    if "w_to" in df.columns:
        df["w_to"] = df["w_to"].fillna(10**12)

    # Normal match
    m = df[(df["w_from"] <= weight) & (weight <= df["w_to"])].copy()
    if not m.empty:
        # If multiple, pick the narrowest band
        m["band_width"] = (m["w_to"] - m["w_from"]).abs()
        m = m.sort_values(["band_width", "w_from"], ascending=[True, True])
        return m.iloc[0]

    # Fallback: if weight > max w_to -> pick max band
    if "w_to" in df.columns:
        mx = df["w_to"].max()
        if weight > mx:
            m2 = df[df["w_to"] == mx]
            if not m2.empty:
                return m2.iloc[0]

    return None

def format_money(x):
    if x is None:
        return "-"
    return f"€{x:,.2f}"

# -----------------------------
# Load Data (cached)
# -----------------------------
@st.cache_data(show_spinner=False)
def load_all_data():
    paths = {
        "dhl_de_plz2_zone": os.path.join(DATA_DIR, "dhl_de_plz2_zone.csv"),
        "dhl_de_rates": os.path.join(DATA_DIR, "dhl_de_rates.csv"),
        "dhl_eu_zone_map": os.path.join(DATA_DIR, "dhl_eu_zone_map.csv"),
        "dhl_eu_rates_long": os.path.join(DATA_DIR, "dhl_eu_rates_long.csv"),
        "raben_zone_map": os.path.join(DATA_DIR, "raben_zone_map.csv"),
        "raben_rates_long": os.path.join(DATA_DIR, "raben_rates_long.csv"),
    }

    data = {}
    for k, p in paths.items():
        data[k] = read_csv_flexible(p)

    # --- normalize DHL DE zone map
    ddz = data["dhl_de_plz2_zone"]
    # expected: plz2, zone
    ddz["plz2"] = ddz["plz2"].apply(norm_plz2)
    ddz["zone"] = pd.to_numeric(ddz["zone"], errors="coerce").astype("Int64")
    data["dhl_de_plz2_zone"] = ddz.dropna(subset=["plz2", "zone"])

    # --- normalize DHL DE rates
    ddr = data["dhl_de_rates"]
    ddr["zone"] = pd.to_numeric(ddr["zone"], errors="coerce").astype("Int64")
    ddr["w_from"] = pd.to_numeric(ddr["w_from"], errors="coerce")
    ddr["w_to"] = pd.to_numeric(ddr["w_to"], errors="coerce")
    ddr["price"] = pd.to_numeric(ddr["price"], errors="coerce")
    data["dhl_de_rates"] = ddr.dropna(subset=["zone", "w_from", "w_to", "price"])

    # --- normalize DHL EU zone map
    dez = data["dhl_eu_zone_map"]
    # expected: country_code, plz2, zone
    dez["country_code"] = dez["country_code"].apply(norm_country_code)
    dez["plz2"] = dez["plz2"].apply(norm_plz2)
    dez["zone"] = pd.to_numeric(dez["zone"], errors="coerce").astype("Int64")
    data["dhl_eu_zone_map"] = dez.dropna(subset=["country_code", "plz2", "zone"])

    # --- normalize DHL EU rates
    der = data["dhl_eu_rates_long"]
    # expected: country_code, zone, w_from, w_to, price
    der["country_code"] = der["country_code"].apply(norm_country_code)
    der["zone"] = pd.to_numeric(der["zone"], errors="coerce").astype("Int64")
    der["w_from"] = pd.to_numeric(der["w_from"], errors="coerce")
    der["w_to"] = pd.to_numeric(der["w_to"], errors="coerce")
    der["price"] = pd.to_numeric(der["price"], errors="coerce")
    data["dhl_eu_rates_long"] = der.dropna(subset=["country_code", "zone", "w_from", "w_to", "price"])

    # --- normalize Raben zone map
    rzm = data["raben_zone_map"]
    # expected: scope, country, plz, zone
    rzm["scope"] = rzm["scope"].astype(str).str.strip().str.upper()
    rzm["country_norm"] = rzm["country"].apply(norm_country_name)
    rzm["plz2"] = rzm["plz"].apply(norm_plz2) if "plz" in rzm.columns else rzm["plz2"].apply(norm_plz2)
    rzm["zone"] = pd.to_numeric(rzm["zone"], errors="coerce").astype("Int64")
    data["raben_zone_map"] = rzm.dropna(subset=["scope", "country_norm", "plz2", "zone"])

    # --- normalize Raben rates
    rrl = data["raben_rates_long"]
    # expected: scope, country, zone, w_from, w_to, price
    rrl["scope"] = rrl["scope"].astype(str).str.strip().str.upper()
    rrl["country_norm"] = rrl["country"].apply(norm_country_name)
    rrl["zone"] = pd.to_numeric(rrl["zone"], errors="coerce").astype("Int64")
    rrl["w_from"] = pd.to_numeric(rrl["w_from"], errors="coerce")
    rrl["w_to"] = pd.to_numeric(rrl["w_to"], errors="coerce")
    rrl["price"] = pd.to_numeric(rrl["price"], errors="coerce")
    data["raben_rates_long"] = rrl.dropna(subset=["scope", "country_norm", "zone", "w_from", "w_to", "price"])

    return data

# -----------------------------
# Business logic
# -----------------------------
def dhl_quote(data, scope, dest_country, dest_plz2, weight, fuel_pct, security_pct):
    try:
        if scope == "DE":
            plz2 = dest_plz2
            ddz = data["dhl_de_plz2_zone"]
            row = ddz[ddz["plz2"] == plz2]
            if row.empty:
                return None, f"DHL: 找不到 DE 的 PLZ2={plz2} 对应 Zone（检查 dhl_de_plz2_zone.csv）"
            zone = int(row.iloc[0]["zone"])

            rates = data["dhl_de_rates"]
            cand = rates[rates["zone"] == zone]
            band = pick_weight_band(cand, weight)
            if band is None:
                return None, f"DHL: 找不到 DE Zone={zone} 的重量段（检查 dhl_de_rates.csv）"

            base = float(band["price"])
            total = base * (1.0 + fuel_pct + security_pct)
            detail = f"DE-{plz2} Zone {zone} | Base {format_money(base)} | Fuel {fuel_pct*100:.2f}% | Security {security_pct*100:.2f}% | Total {format_money(total)}"
            return {"base": base, "total": total, "zone": zone, "detail": detail}, None

        else:  # EU
            # DHL EU expects country_code
            cc = norm_country_code(dest_country)
            plz2 = dest_plz2
            zmap = data["dhl_eu_zone_map"]
            row = zmap[(zmap["country_code"] == cc) & (zmap["plz2"] == plz2)]
            if row.empty:
                return None, f"DHL: 找不到 EU 的 {cc}-{plz2} 对应 Zone（检查 dhl_eu_zone_map.csv）"
            zone = int(row.iloc[0]["zone"])

            rates = data["dhl_eu_rates_long"]
            cand = rates[(rates["country_code"] == cc) & (rates["zone"] == zone)]
            band = pick_weight_band(cand, weight)
            if band is None:
                return None, f"DHL: 找不到 EU {cc} Zone={zone} 的重量段（检查 dhl_eu_rates_long.csv）"

            base = float(band["price"])
            total = base * (1.0 + fuel_pct + security_pct)
            detail = f"{cc}-{plz2} Zone {zone} | Base {format_money(base)} | Fuel {fuel_pct*100:.2f}% | Security {security_pct*100:.2f}% | Total {format_money(total)}"
            return {"base": base, "total": total, "zone": zone, "detail": detail}, None

    except Exception as e:
        return None, f"DHL 系统错误：{e}"

def raben_quote(data, scope, dest_country, dest_plz2, weight, daf_pct, adr, avis, insurance_value, adr_fee, avis_fee, insurance_min):
    try:
        plz2 = dest_plz2

        # Normalize country input to match raben tables (which are country names, not ISO codes)
        # We allow user input: "PL", "Poland", "Polen" etc.
        user = norm_country_name(dest_country)
        alias = {
            "pl": "polen",
            "poland": "polen",
            "polen": "polen",
            "de": "deutschland",
            "germany": "deutschland",
            "deutschland": "deutschland",
            "bg": "bulgarien",
            "bulgaria": "bulgarien",
            "bulgarien": "bulgarien",
            "lv": "lettland",
            "latvia": "lettland",
            "lettland": "lettland",
        }
        country_norm = alias.get(user, user)

        # For scope DE, force country=Deutschland (avoid user typo breaking DE)
        if scope == "DE":
            country_norm = "deutschland"

        zmap = data["raben_zone_map"]
        row = zmap[(zmap["scope"] == scope) & (zmap["country_norm"] == country_norm) & (zmap["plz2"] == plz2)]
        if row.empty:
            return None, f"Raben: 找不到 {scope}/{dest_country}/PLZ2={plz2} 的 Zone（检查 raben_zone_map.csv）"
        zone = int(row.iloc[0]["zone"])

        rates = data["raben_rates_long"]
        cand = rates[(rates["scope"] == scope) & (rates["country_norm"] == country_norm) & (rates["zone"] == zone)]
        band = pick_weight_band(cand, weight)
        if band is None:
            return None, f"Raben: 找不到 {scope}/{dest_country} Zone={zone} 的重量段（检查 raben_rates_long.csv 的 w_from/w_to）"

        base = float(band["price"])

        fees = 0.0
        if adr:
            fees += adr_fee
        if avis:
            fees += avis_fee
        if insurance_value and insurance_value > 0:
            fees += insurance_min

        total = base * (1.0 + daf_pct) + fees

        # Display pretty country (use original table country if possible)
        display_country = row.iloc[0]["country"] if "country" in row.columns else dest_country

        parts = [
            f"{display_country} Zone {zone}",
            f"Base {format_money(base)}",
            f"DAF {daf_pct*100:.2f}%",
        ]
        if adr:
            parts.append(f"ADR {format_money(adr_fee)}")
        if avis:
            parts.append(f"Avis {format_money(avis_fee)}")
        if insurance_value and insurance_value > 0:
            parts.append(f"InsuranceMin {format_money(insurance_min)}")
        parts.append(f"Total {format_money(total)}")

        detail = " | ".join(parts)
        return {"base": base, "total": total, "zone": zone, "detail": detail}, None

    except Exception as e:
        return None, f"Raben 系统错误：{e}"

# -----------------------------
# UI
# -----------------------------
st.title("🚚 Aifuge 双承运商报价系统（生产版）")

data = None
try:
    data = load_all_data()
except Exception as e:
    st.error(f"数据加载失败：{e}")
    st.stop()

with st.sidebar:
    st.header("⚙️ 参数")

    dhl_fuel_pct = st.number_input("DHL Fuel %", min_value=0.0, max_value=2.0, value=0.12, step=0.01, format="%.2f")
    dhl_security_pct = st.number_input("DHL Sicherheitszuschlag %", min_value=0.0, max_value=2.0, value=0.00, step=0.01, format="%.2f")

    raben_daf_pct = st.number_input("Raben DAF %", min_value=0.0, max_value=2.0, value=0.10, step=0.01, format="%.2f")

    st.divider()
    st.subheader("Raben 附加费（可选）")
    adr_fee = st.number_input("Raben ADR Fee €", min_value=0.0, value=12.50, step=0.50, format="%.2f")
    avis_fee = st.number_input("Raben Avis Fee €", min_value=0.0, value=12.00, step=0.50, format="%.2f")
    insurance_min = st.number_input("Raben Insurance Min €", min_value=0.0, value=5.95, step=0.10, format="%.2f")

st.subheader("📦 输入")

c1, c2, c3 = st.columns([2, 2, 2])
with c1:
    scope = st.selectbox("Scope", ["DE", "EU"], index=0)
    dest_country = st.text_input("Destination Country（可输入：Polen/PL/波兰 等）", value="Deutschland" if scope == "DE" else "Polen")
with c2:
    weight = st.number_input("Actual Weight (kg)", min_value=0.01, value=200.00, step=10.00, format="%.2f")
with c3:
    plz_input = st.text_input("Destination PLZ（前2位）", value="38" if scope == "DE" else "44")
    dest_plz2 = norm_plz2(plz_input)

c4, c5, c6 = st.columns([2, 2, 2])
with c4:
    adr = st.checkbox("ADR（危险品）", value=False)
with c5:
    avis = st.checkbox("Avis/预约派送", value=False)
with c6:
    insurance_value = st.number_input("Insurance Value €（可选）", min_value=0.0, value=0.0, step=100.0, format="%.2f")

btn = st.button("💰 计算报价")

st.divider()
st.subheader("📊 结果（Netto）")
left, right = st.columns(2)

if btn:
    # DHL
    dhl_res, dhl_err = dhl_quote(
        data=data,
        scope=scope,
        dest_country=dest_country,
        dest_plz2=dest_plz2,
        weight=weight,
        fuel_pct=dhl_fuel_pct,
        security_pct=dhl_security_pct,
    )
    # Raben
    raben_res, raben_err = raben_quote(
        data=data,
        scope=scope,
        dest_country=dest_country,
        dest_plz2=dest_plz2,
        weight=weight,
        daf_pct=raben_daf_pct,
        adr=adr,
        avis=avis,
        insurance_value=insurance_value,
        adr_fee=adr_fee,
        avis_fee=avis_fee,
        insurance_min=insurance_min,
    )

    with left:
        st.markdown("### DHL Freight")
        if dhl_err:
            st.error(dhl_err)
        else:
            st.success(dhl_res["detail"])

    with right:
        st.markdown("### Raben")
        if raben_err:
            st.error(raben_err)
        else:
            st.success(raben_res["detail"])

else:
    st.info("填写参数后点击 **计算报价**。")

st.caption("提示：如果你刚刚覆盖了 data/ 的 CSV，Streamlit Cloud 可能需要 10~30 秒自动刷新缓存。")

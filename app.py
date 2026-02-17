import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Aifuge 双承运商报价系统（生产版）", layout="wide")

DATA_DIR = "data"

# ----------------------------
# Helpers: robust CSV loader
# ----------------------------
def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df

def read_csv_robust(path: str) -> pd.DataFrame:
    """
    Robustly read CSV that may be separated by comma/semicolon/pipe/tab.
    Also fixes the common broken case where the whole header becomes one column like 'plz2|zone'.
    """
    # Try sniffing delimiter first
    try:
        df = pd.read_csv(path, sep=None, engine="python")
    except Exception:
        # fallback
        df = pd.read_csv(path)

    df = _normalize_cols(df)

    # If only one column and it contains delimiters, split it.
    if df.shape[1] == 1:
        col0 = df.columns[0]
        # Try splitting header column name by | ; , tab
        if any(d in col0 for d in ["|", ";", ",", "\t"]):
            # re-read with a better separator guess
            for sep in ["|", ";", ",", "\t"]:
                try:
                    df2 = pd.read_csv(path, sep=sep)
                    df2 = _normalize_cols(df2)
                    if df2.shape[1] > 1:
                        df = df2
                        break
                except Exception:
                    pass

    # Strip whitespace from string cells
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip()

    return df

def plz2_to_int(x) -> int | None:
    if x is None:
        return None
    s = str(x).strip()
    if s == "":
        return None
    # keep only digits
    s = re.sub(r"\D", "", s)
    if s == "":
        return None
    # if user typed 38110, take first 2 digits
    if len(s) >= 2:
        s = s[:2]
    return int(s)

def weight_to_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def find_rate_bracket(df: pd.DataFrame, w: float, w_from_col="w_from", w_to_col="w_to") -> pd.Series | None:
    """
    Picks the row where w_from <= w <= w_to (inclusive upper bound).
    """
    if df.empty:
        return None
    tmp = df.copy()
    tmp[w_from_col] = pd.to_numeric(tmp[w_from_col], errors="coerce")
    tmp[w_to_col] = pd.to_numeric(tmp[w_to_col], errors="coerce")

    m = (tmp[w_from_col].fillna(-1e18) <= w) & (w <= tmp[w_to_col].fillna(1e18))
    hit = tmp[m]
    if hit.empty:
        return None
    # In case multiple, choose the smallest w_to
    hit = hit.sort_values(by=[w_to_col, w_from_col], ascending=[True, True])
    return hit.iloc[0]

# ----------------------------
# Country normalization
# ----------------------------
COUNTRY_ALIASES_TO_DE = {
    # Germany
    "de": "deutschland",
    "germany": "deutschland",
    "deutschland": "deutschland",

    # Poland
    "pl": "polen",
    "poland": "polen",
    "polen": "polen",

    # Bulgaria
    "bg": "bulgarien",
    "bulgaria": "bulgarien",
    "bulgarien": "bulgarien",

    # Latvia
    "lv": "lettland",
    "latvia": "lettland",
    "lettland": "lettland",
}

COUNTRY_DE_TO_CODE = {
    "deutschland": "DE",
    "polen": "PL",
    "bulgarien": "BG",
    "lettland": "LV",
}

def normalize_country_input(s: str) -> tuple[str, str]:
    """
    Returns (country_de, country_code)
    """
    s0 = (s or "").strip().lower()
    s0 = re.sub(r"\s+", " ", s0)
    country_de = COUNTRY_ALIASES_TO_DE.get(s0, s0)  # fallback to itself
    country_code = COUNTRY_DE_TO_CODE.get(country_de, country_de.upper()[:2])
    return country_de, country_code

# ----------------------------
# Load data
# ----------------------------
@st.cache_data(show_spinner=False)
def load_all_data():
    dhl_de_plz2_zone = read_csv_robust(f"{DATA_DIR}/dhl_de_plz2_zone.csv")
    dhl_de_rates = read_csv_robust(f"{DATA_DIR}/dhl_de_rates.csv")

    dhl_eu_zone_map = read_csv_robust(f"{DATA_DIR}/dhl_eu_zone_map.csv")
    dhl_eu_rates_long = read_csv_robust(f"{DATA_DIR}/dhl_eu_rates_long.csv")

    raben_zone_map = read_csv_robust(f"{DATA_DIR}/raben_zone_map.csv")
    raben_rates_long = read_csv_robust(f"{DATA_DIR}/raben_rates_long.csv")

    return {
        "dhl_de_plz2_zone": dhl_de_plz2_zone,
        "dhl_de_rates": dhl_de_rates,
        "dhl_eu_zone_map": dhl_eu_zone_map,
        "dhl_eu_rates_long": dhl_eu_rates_long,
        "raben_zone_map": raben_zone_map,
        "raben_rates_long": raben_rates_long,
    }

data = load_all_data()

# ----------------------------
# UI
# ----------------------------
st.title("🚚 Aifuge 双承运商报价系统（生产版）")

with st.sidebar:
    st.header("⚙️ 参数")
    dhl_fuel_pct = st.number_input("DHL Fuel %", value=0.12, step=0.01, format="%.2f")
    dhl_sec_pct = st.number_input("DHL Sicherheitszuschlag %", value=0.00, step=0.01, format="%.2f")
    raben_daf_pct = st.number_input("Raben DAF %", value=0.10, step=0.01, format="%.2f")

st.subheader("📦 输入")

c1, c2, c3 = st.columns([2, 2, 2])
with c1:
    scope = st.selectbox("Scope", ["DE", "EU"], index=0)
with c2:
    weight = st.number_input("Actual Weight (kg)", value=200.0, step=10.0, format="%.2f")
with c3:
    plz2_in = st.text_input("Destination PLZ (前2位)", value="38")

dest_country_in = st.text_input("Destination Country（可输入：Polen/PL/波兰 等）", value="Deutschland")

btn = st.button("💰 计算报价")

# ----------------------------
# Calculations
# ----------------------------
def calc_dhl(scope: str, country_code: str, plz2: int, weight: float):
    if scope == "DE":
        zmap = data["dhl_de_plz2_zone"].copy()
        zmap["plz2"] = pd.to_numeric(zmap.get("plz2"), errors="coerce")
        zrow = zmap[zmap["plz2"] == plz2]
        if zrow.empty:
            return None, f"DHL: 找不到 DE 的 PLZ2={plz2} 对应 Zone（检查 dhl_de_plz2_zone.csv）"
        zone = int(zrow.iloc[0]["zone"])

        rates = data["dhl_de_rates"].copy()
        rates["zone"] = pd.to_numeric(rates.get("zone"), errors="coerce")
        rates = rates[rates["zone"] == zone]
        r = find_rate_bracket(rates, weight, "w_from", "w_to")
        if r is None:
            return None, f"DHL: 无法匹配重量段（检查 dhl_de_rates.csv）"
        base = float(r["price"])
        total = base * (1 + dhl_fuel_pct + dhl_sec_pct)
        return {
            "zone": zone,
            "base": base,
            "fuel_pct": dhl_fuel_pct,
            "sec_pct": dhl_sec_pct,
            "total": total,
        }, None

    # EU
    zmap = data["dhl_eu_zone_map"].copy()
    zmap["plz2"] = pd.to_numeric(zmap.get("plz2"), errors="coerce")
    zmap["country_code"] = zmap.get("country_code").astype(str).str.upper().str.strip()

    zrow = zmap[(zmap["country_code"] == country_code) & (zmap["plz2"] == plz2)]
    if zrow.empty:
        return None, f"DHL: 找不到 EU 的 {country_code}-{plz2} 对应 Zone（检查 dhl_eu_zone_map.csv）"
    zone = int(zrow.iloc[0]["zone"])

    rates = data["dhl_eu_rates_long"].copy()
    rates["country_code"] = rates.get("country_code").astype(str).str.upper().str.strip()
    rates["zone"] = pd.to_numeric(rates.get("zone"), errors="coerce")
    rates = rates[(rates["country_code"] == country_code) & (rates["zone"] == zone)]

    r = find_rate_bracket(rates, weight, "w_from", "w_to")
    if r is None:
        return None, f"DHL: 无法匹配 EU 重量段（检查 dhl_eu_rates_long.csv 的 w_from/w_to）"

    base = float(r["price"])
    total = base * (1 + dhl_fuel_pct + dhl_sec_pct)
    return {
        "zone": zone,
        "base": base,
        "fuel_pct": dhl_fuel_pct,
        "sec_pct": dhl_sec_pct,
        "total": total,
    }, None

def calc_raben(scope: str, country_de: str, plz2: int, weight: float):
    zmap = data["raben_zone_map"].copy()
    # normalize
    zmap["scope"] = zmap.get("scope").astype(str).str.upper().str.strip()
    zmap["country"] = zmap.get("country").astype(str).str.lower().str.strip()
    zmap["plz2"] = pd.to_numeric(zmap.get("plz2"), errors="coerce")

    zrow = zmap[(zmap["scope"] == scope) & (zmap["country"] == country_de) & (zmap["plz2"] == plz2)]
    if zrow.empty:
        return None, f"Raben: 找不到 {scope}/{country_de}/PLZ2={plz2} 的 Zone（检查 raben_zone_map.csv）"
    zone = int(zrow.iloc[0]["zone"])

    rates = data["raben_rates_long"].copy()
    rates["scope"] = rates.get("scope").astype(str).str.upper().str.strip()
    rates["country"] = rates.get("country").astype(str).str.lower().str.strip()
    rates["zone"] = pd.to_numeric(rates.get("zone"), errors="coerce")
    rates = rates[(rates["scope"] == scope) & (rates["country"] == country_de) & (rates["zone"] == zone)]

    r = find_rate_bracket(rates, weight, "w_from", "w_to")
    if r is None:
        return None, f"Raben: 无法匹配重量段（检查 raben_rates_long.csv 的 w_from/w_to，是否已到 5000kg）"

    base = float(r["price"])
    total = base * (1 + raben_daf_pct)
    return {
        "zone": zone,
        "base": base,
        "daf_pct": raben_daf_pct,
        "total": total,
    }, None

# ----------------------------
# Run
# ----------------------------
st.markdown("---")
st.subheader("📊 结果（Netto）")

if btn:
    plz2 = plz2_to_int(plz2_in)
    if plz2 is None:
        st.error("请输入有效的 PLZ 前2位（例如 38 / 44 / 00）")
        st.stop()

    country_de, country_code = normalize_country_input(dest_country_in)

    left, right = st.columns(2)

    with left:
        st.markdown("### DHL Freight")
        res, err = calc_dhl(scope, country_code, plz2, weight_to_float(weight))
        if err:
            st.error(err)
        else:
            st.success(
                f"{country_code}-{plz2:02d} Zone {res['zone']} | "
                f"Base €{res['base']:.2f} | Fuel {res['fuel_pct']*100:.2f}% | "
                f"Security {res['sec_pct']*100:.2f}% | Total €{res['total']:.2f}"
            )

    with right:
        st.markdown("### Raben")
        res, err = calc_raben(scope, country_de, plz2, weight_to_float(weight))
        if err:
            st.error(err)
        else:
            st.success(
                f"{country_de.title()} Zone {res['zone']} | "
                f"Base €{res['base']:.2f} | DAF {res['daf_pct']*100:.2f}% | Total €{res['total']:.2f}"
            )

st.caption("提示：如果你刚覆盖了 data/ 的 CSV，Streamlit Cloud 可能需要 10-30 秒自动重启刷新。")

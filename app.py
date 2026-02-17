import json
import hashlib
from pathlib import Path
import pandas as pd
import streamlit as st

# ---------------------------
# 基础配置
# ---------------------------
APP_TITLE = "🚛 Aifuge 双承运商报价系统（生产版）"
DATA_DIR = Path("data")

WAREHOUSES = {
    "38110 Braunschweig": "Im Steinkampe 10, 38110 Braunschweig",
    "38112 Braunschweig": "Hansestrasse 76, 38112 Braunschweig",
    "30855 Langenhagen": "Berliner Allee 59, 30855 Langenhagen",
}

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def load_csv(name: str) -> pd.DataFrame:
    p = DATA_DIR / name
    if not p.exists():
        st.error(f"缺少数据文件：{p.as_posix()}")
        st.stop()
    return pd.read_csv(p)

def load_params() -> dict:
    p = DATA_DIR / "params_default.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

def get_secret(key: str, default=None):
    # Streamlit Cloud → App settings → Secrets
    return st.secrets.get(key, default) if hasattr(st, "secrets") else default

# ---------------------------
# 登录保护（可选，强烈建议）
# ---------------------------
def require_login():
    """
    开关：
      - 在 Streamlit Secrets 里设置：
        AUTH_ENABLED = "1"
        AUTH_USER = "aifuge"
        AUTH_PASS_SHA256 = "<sha256(password)>"
    """
    enabled = str(get_secret("AUTH_ENABLED", "0")) == "1"
    if not enabled:
        return True

    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    if st.session_state.auth_ok:
        return True

    st.sidebar.header("🔐 登录")
    u = st.sidebar.text_input("用户名", value="", placeholder="例如 aifuge")
    p = st.sidebar.text_input("密码", value="", type="password")

    if st.sidebar.button("登录"):
        exp_user = str(get_secret("AUTH_USER", ""))
        exp_pass = str(get_secret("AUTH_PASS_SHA256", ""))
        if u == exp_user and sha256(p) == exp_pass:
            st.session_state.auth_ok = True
            st.success("登录成功")
            st.rerun()
        else:
            st.error("用户名或密码错误")

    st.stop()

# ---------------------------
# 运价计算工具函数
# ---------------------------
def plz2(plz: str) -> str:
    s = "".join([c for c in str(plz) if c.isdigit()])
    return (s[:2] if len(s) >= 2 else "").zfill(2) if s else ""

def chargeable_weight_raben(actual_kg: float, cbm: float, ldm: float, packaging: str) -> float:
    # 你报价文件口径的简化实现：MAX(实重, 最低计费重量, CBM*200, LDM*1000)
    minw = {
        "Cartons": 15,
        "Halfpallet": 100,
        "Europalette": 200,
        "OtherPallet": 300,
    }.get(packaging, 300)
    return max(actual_kg, minw, cbm * 200.0, ldm * 1000.0)

def pick_price_by_weight(df: pd.DataFrame, weight: float) -> float | None:
    # df: weight_max asc
    cand = df[df["weight_max"] >= weight]
    if cand.empty:
        return None
    return float(cand.sort_values("weight_max").iloc[0]["price"])

# ---------------------------
# 加载数据
# ---------------------------
@st.cache_data(show_spinner=False)
def load_all_data():
    dhl_de_rates = load_csv("dhl_de_rates.csv")  # columns: zone, weight_max, price
    dhl_de_zmap  = load_csv("dhl_de_plz2_zone.csv")  # columns: plz2, zone
    dhl_eu_rates = load_csv("dhl_eu_rates_long.csv")  # columns: country_code, zone, weight_max, price
    dhl_eu_zmap  = load_csv("dhl_eu_zone_map.csv")  # columns: country_code, plz2, zone

    raben_rates  = load_csv("raben_rates_long.csv")  # columns: scope, country, zone, w_from, w_to, price
    raben_zmap   = load_csv("raben_zone_map.csv")    # columns: scope, country, plz2, zone
    raben_diesel = load_csv("raben_diesel_floater.csv")  # columns: diesel_cent_per_l_max, surcharge_pct

    params = load_params()
    return dhl_de_rates, dhl_de_zmap, dhl_eu_rates, dhl_eu_zmap, raben_rates, raben_zmap, raben_diesel, params

def diesel_pct_from_floater(df: pd.DataFrame, diesel_cent: float) -> float:
    # 取 <= diesel 的最后一档；若柴油价低于最小档，返回 0
    df = df.sort_values("diesel_cent_per_l_max")
    cand = df[df["diesel_cent_per_l_max"] >= diesel_cent]
    if cand.empty:
        # 超出最大档：取最大档
        return float(df.iloc[-1]["surcharge_pct"])
    return float(cand.iloc[0]["surcharge_pct"])

def calc_dhl(scope: str, country_code: str, dest_plz: str, weight_kg: float,
             dhl_fuel_pct: float, dhl_security_pct: float,
             dhl_de_rates: pd.DataFrame, dhl_de_zmap: pd.DataFrame,
             dhl_eu_rates: pd.DataFrame, dhl_eu_zmap: pd.DataFrame):
    p2 = plz2(dest_plz)
    if not p2:
        return None

    if scope == "DE":
        z = dhl_de_zmap.loc[dhl_de_zmap["plz2"] == p2, "zone"]
        if z.empty:
            return None
        zone = int(z.iloc[0])
        base_df = dhl_de_rates[(dhl_de_rates["zone"] == zone)].copy()
        base = pick_price_by_weight(base_df, weight_kg)
        if base is None:
            return None
    else:
        z = dhl_eu_zmap.loc[(dhl_eu_zmap["country_code"] == country_code) & (dhl_eu_zmap["plz2"] == p2), "zone"]
        if z.empty:
            return None
        zone = int(z.iloc[0])
        base_df = dhl_eu_rates[(dhl_eu_rates["country_code"] == country_code) & (dhl_eu_rates["zone"] == zone)].copy()
        base = pick_price_by_weight(base_df, weight_kg)
        if base is None:
            return None

    fuel = base * dhl_fuel_pct
    sec  = base * dhl_security_pct
    total = base + fuel + sec

    return {
        "zone": zone,
        "base": base,
        "fuel": fuel,
        "security": sec,
        "total": total,
        "currency": "EUR",
    }

def calc_raben(scope: str, country: str, dest_plz: str, actual_kg: float, cbm: float, ldm: float, packaging: str,
               adr: bool, avis: bool, insurance_value: float,
               daf_pct: float, mobility_pct: float, diesel_cent: float,
               adr_fee: float, avis_fee: float, ins_fee_min: float,
               raben_rates: pd.DataFrame, raben_zmap: pd.DataFrame, raben_diesel: pd.DataFrame):
    p2 = plz2(dest_plz)
    if not p2:
        return None

    z = raben_zmap.loc[(raben_zmap["scope"] == scope) & (raben_zmap["country"] == country) & (raben_zmap["plz2"] == p2), "zone"]
    if z.empty:
        return None
    zone = int(z.iloc[0])

    cw = chargeable_weight_raben(actual_kg, cbm, ldm, packaging)

    # 找到对应区间 w_from < cw <= w_to 的价格
    cand = raben_rates[
        (raben_rates["scope"] == scope) &
        (raben_rates["country"] == country) &
        (raben_rates["zone"] == zone) &
        (raben_rates["w_from"] < cw) &
        (raben_rates["w_to"] >= cw)
    ].copy()
    if cand.empty:
        return None
    base = float(cand.iloc[0]["price"])

    diesel_pct = diesel_pct_from_floater(raben_diesel, diesel_cent)
    diesel_amt = base * diesel_pct

    daf_amt = base * daf_pct
    mob_amt = base * mobility_pct

    adr_amt = adr_fee if adr else 0.0
    avis_amt = avis_fee if avis else 0.0
    ins_amt = ins_fee_min if insurance_value and insurance_value > 0 else 0.0

    total = base + diesel_amt + daf_amt + mob_amt + adr_amt + avis_amt + ins_amt

    return {
        "zone": zone,
        "chargeable_weight": cw,
        "base": base,
        "diesel_pct": diesel_pct,
        "diesel": diesel_amt,
        "daf": daf_amt,
        "mobility": mob_amt,
        "adr": adr_amt,
        "avis": avis_amt,
        "insurance": ins_amt,
        "total": total,
        "currency": "EUR",
    }

# ---------------------------
# UI
# ---------------------------
st.set_page_config(page_title="Aifuge Quote Engine", layout="wide")
st.title(APP_TITLE)

require_login()

(dhl_de_rates, dhl_de_zmap, dhl_eu_rates, dhl_eu_zmap,
 raben_rates, raben_zmap, raben_diesel, params) = load_all_data()

# 参数默认值
DEFAULTS = {
    "dhl_fuel_pct": float(params.get("dhl_fuel_pct", 0.12)),
    "dhl_security_pct": float(params.get("dhl_security_pct", 0.00)),
    "raben_daf_pct": float(params.get("raben_daf_pct", 0.10)),
    "raben_mobility_pct": float(params.get("raben_mobility_pct", 0.029)),
    "raben_adr_fee": float(params.get("raben_adr_fee", 12.50)),
    "raben_avis_fee": float(params.get("raben_avis_fee", 12.00)),
    "raben_ins_min": float(params.get("raben_ins_min", 5.95)),
    "raben_diesel_cent": float(params.get("raben_diesel_cent", 130.00)),
}

with st.sidebar:
    st.header("🏭 发货仓（固定）")
    wh = st.selectbox("Origin Warehouse", list(WAREHOUSES.keys()), index=0)
    st.caption(WAREHOUSES[wh])

    st.divider()
    st.header("⚙️ 参数（管理员维护）")
    dhl_fuel_pct = st.number_input("DHL Fuel %", min_value=0.0, max_value=1.0, value=DEFAULTS["dhl_fuel_pct"], step=0.01, format="%.2f")
    dhl_sec_pct  = st.number_input("DHL Sicherheitszuschlag %", min_value=0.0, max_value=1.0, value=DEFAULTS["dhl_security_pct"], step=0.01, format="%.2f")

    raben_diesel_cent = st.number_input("Raben Diesel (cent/L)", min_value=0.0, value=DEFAULTS["raben_diesel_cent"], step=1.0, format="%.2f")
    raben_daf_pct     = st.number_input("Raben DAF %", min_value=0.0, max_value=1.0, value=DEFAULTS["raben_daf_pct"], step=0.01, format="%.3f")
    raben_mob_pct     = st.number_input("Raben Mobilitäts-Floater %", min_value=0.0, max_value=1.0, value=DEFAULTS["raben_mobility_pct"], step=0.001, format="%.3f")

    raben_adr_fee     = st.number_input("Raben ADR Fee €", min_value=0.0, value=DEFAULTS["raben_adr_fee"], step=0.50, format="%.2f")
    raben_avis_fee    = st.number_input("Raben Avis Fee €", min_value=0.0, value=DEFAULTS["raben_avis_fee"], step=0.50, format="%.2f")
    raben_ins_min     = st.number_input("Raben Insurance Min €", min_value=0.0, value=DEFAULTS["raben_ins_min"], step=0.50, format="%.2f")

st.subheader("📥 输入")
c1, c2, c3 = st.columns(3)

with c1:
    scope = st.selectbox("Scope（DE/EU）", ["DE", "EU"], index=0)
    dest_country = st.text_input("Destination Country（按你Raben国家名称）", value="Deutschland")
    dest_plz = st.text_input("Destination PLZ（至少前2位）", value="38110")

with c2:
    weight = st.number_input("Actual Weight (kg)", min_value=0.1, value=200.0, step=1.0)
    cbm = st.number_input("CBM（可选）", min_value=0.0, value=0.0, step=0.01)
    ldm = st.number_input("LDM（可选）", min_value=0.0, value=0.0, step=0.01)

with c3:
    packaging = st.selectbox("Packaging Type", ["Cartons", "Halfpallet", "Europalette", "OtherPallet"], index=2)
    adr = st.checkbox("ADR（危险品）", value=False)
    avis = st.checkbox("Avis/预约派送", value=False)
    insurance_value = st.number_input("Insurance Value €（可选）", min_value=0.0, value=0.0, step=10.0)

st.divider()

# DHL EU 需要 country_code：这里先做一个最简单映射（你后续我们可以做成下拉+完整映射表）
COUNTRY_CODE_MAP = {
    "Deutschland": "DE",
    "Österreich": "AT",
    "Polen": "PL",
    "Bulgarien": "BG",
    "Lettland": "LV",
    "Litauen": "LT",
    "Estland": "EE",
    "Tschechien": "CZ",
    "Ungarn": "HU",
    "Rumänien": "RO",
    "Niederlande": "NL",
    "Belgien": "BE",
    "Frankreich": "FR",
    "Italien": "IT",
    "Spanien": "ES",
    "Portugal": "PT",
    "Dänemark": "DK",
    "Schweden": "SE",
    "Finnland": "FI",
    "Irland": "IE",
    "Griechenland": "GR",
    "Slowakei": "SK",
    "Slowenien": "SI",
    "Kroatien": "HR",
    "Luxemburg": "LU",
}
country_code = COUNTRY_CODE_MAP.get(dest_country, "")

if st.button("🧮 计算报价", type="primary"):
    dhl = calc_dhl(
        scope=scope,
        country_code=country_code,
        dest_plz=dest_plz,
        weight_kg=weight,
        dhl_fuel_pct=dhl_fuel_pct,
        dhl_security_pct=dhl_sec_pct,
        dhl_de_rates=dhl_de_rates, dhl_de_zmap=dhl_de_zmap,
        dhl_eu_rates=dhl_eu_rates, dhl_eu_zmap=dhl_eu_zmap,
    )

    raben = calc_raben(
        scope=scope,
        country=dest_country,
        dest_plz=dest_plz,
        actual_kg=weight,
        cbm=cbm,
        ldm=ldm,
        packaging=packaging,
        adr=adr,
        avis=avis,
        insurance_value=insurance_value,
        daf_pct=raben_daf_pct,
        mobility_pct=raben_mob_pct,
        diesel_cent=raben_diesel_cent,
        adr_fee=raben_adr_fee,
        avis_fee=raben_avis_fee,
        ins_fee_min=raben_ins_min,
        raben_rates=raben_rates,
        raben_zmap=raben_zmap,
        raben_diesel=raben_diesel,
    )

    st.subheader("📌 结果（透明明细，Netto）")
    colA, colB = st.columns(2)

    with colA:
        st.markdown("### DHL Freight")
        if not dhl:
            st.error("DHL：无法匹配分区/重量段（检查国家/PLZ/数据表）")
        else:
            st.write({
                "Zone": dhl["zone"],
                "Base": round(dhl["base"], 2),
                "Fuel": round(dhl["fuel"], 2),
                "Security": round(dhl["security"], 2),
                "Total": round(dhl["total"], 2),
            })

    with colB:
        st.markdown("### Raben")
        if not raben:
            st.error("Raben：无法匹配分区/重量段（检查国家/PLZ/数据表）")
        else:
            st.write({
                "Zone": raben["zone"],
                "Chargeable kg": round(raben["chargeable_weight"], 2),
                "Base": round(raben["base"], 2),
                "Diesel": round(raben["diesel"], 2),
                "DAF": round(raben["daf"], 2),
                "Mobility": round(raben["mobility"], 2),
                "ADR": round(raben["adr"], 2),
                "Avis": round(raben["avis"], 2),
                "Insurance": round(raben["insurance"], 2),
                "Total": round(raben["total"], 2),
            })

    if dhl and raben:
        cheaper = "DHL" if dhl["total"] < raben["total"] else "Raben"
        st.success(f"成本更低（仅成本比较）：**{cheaper}**")

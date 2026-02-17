import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="Aifuge Quote System", layout="wide")
st.title("🚛 Aifuge 双承运商报价系统（生产版）")

DATA_DIR = "data"

def read_csv_safe(path: str) -> pd.DataFrame:
    full = os.path.join(DATA_DIR, path)
    df = pd.read_csv(full)
    # 统一列名去空格
    df.columns = [c.strip() for c in df.columns]
    return df

def ensure_col(df: pd.DataFrame, candidates, target_name: str) -> pd.DataFrame:
    """把 candidates 中存在的列重命名为 target_name（如果 target_name 不存在）"""
    if target_name in df.columns:
        return df
    for c in candidates:
        if c in df.columns:
            return df.rename(columns={c: target_name})
    return df  # 留给上层报错提示

def normalize_zone_map(df: pd.DataFrame) -> pd.DataFrame:
    # 让 zone_map 至少有 plz / zone
    df = ensure_col(df, ["plz2", "plz_prefix", "postal_prefix"], "plz")
    df = ensure_col(df, ["Zone", "ZONE"], "zone")
    return df

def normalize_rates(df: pd.DataFrame) -> pd.DataFrame:
    # 让 rates 至少有 w_from / w_to / price / zone
    df = ensure_col(df, ["weight_from", "from", "wfrom"], "w_from")
    df = ensure_col(df, ["weight_to", "to", "wto"], "w_to")
    df = ensure_col(df, ["rate", "Rate", "preis", "Price"], "price")
    df = ensure_col(df, ["Zone", "ZONE"], "zone")
    return df

def to_str_plz2(x) -> str:
    s = str(x).strip()
    # 如果用户输入 38110，就取前两位；如果输入 38 就是 38
    if len(s) >= 2:
        return s[:2]
    return s

def pick_zone_de(dhl_de_zone: pd.DataFrame, plz2: str):
    # dhl_de_plz2_zone.csv 可能是 plz2 或 plz
    zdf = normalize_zone_map(dhl_de_zone)
    if "plz" not in zdf.columns:
        raise KeyError("DHL DE zone_map 缺少 plz/plz2 列")
    if "zone" not in zdf.columns:
        raise KeyError("DHL DE zone_map 缺少 zone 列")
    match = zdf[zdf["plz"].astype(str).str.zfill(2) == plz2]
    if match.empty:
        return None
    return int(match.iloc[0]["zone"])

def pick_zone_eu(dhl_eu_zone: pd.DataFrame, country_code: str, plz2: str):
    zdf = normalize_zone_map(dhl_eu_zone)
    # EU zone_map 必须有 country_code
    zdf = ensure_col(zdf, ["country", "country_code", "cc"], "country_code")
    if "country_code" not in zdf.columns:
        raise KeyError("DHL EU zone_map 缺少 country_code 列")
    if "plz" not in zdf.columns:
        raise KeyError("DHL EU zone_map 缺少 plz/plz2 列")
    match = zdf[
        (zdf["country_code"].astype(str).str.strip() == country_code) &
        (zdf["plz"].astype(str).str.zfill(2) == plz2)
    ]
    if match.empty:
        return None
    return int(match.iloc[0]["zone"])

def pick_rate(df_rates: pd.DataFrame, zone: int, weight: float):
    rdf = normalize_rates(df_rates)
    if not all(c in rdf.columns for c in ["zone", "w_from", "w_to", "price"]):
        missing = [c for c in ["zone","w_from","w_to","price"] if c not in rdf.columns]
        raise KeyError(f"rates 表缺列: {missing}")
    # 注意：w_to 用 “>= weight” 或 “> weight” 都行，这里用 >= 覆盖边界
    m = rdf[
        (rdf["zone"].astype(int) == int(zone)) &
        (rdf["w_from"].astype(float) <= float(weight)) &
        (rdf["w_to"].astype(float) >= float(weight))
    ]
    if m.empty:
        return None
    return float(m.iloc[0]["price"])

# ===== 侧边参数（管理员）=====
st.sidebar.header("⚙ 参数")
dhl_fuel = st.sidebar.number_input("DHL Fuel %", value=0.12, step=0.01)
raben_daf = st.sidebar.number_input("Raben DAF %", value=0.10, step=0.01)

# ===== 输入区 =====
st.header("📦 输入")

c1, c2, c3 = st.columns(3)
with c1:
    scope = st.selectbox("Scope", ["DE", "EU"])
with c2:
    weight = st.number_input("Actual Weight (kg)", value=200.0, step=1.0)
with c3:
    plz_input = st.text_input("Destination PLZ (前2位)", value="38")

plz2 = to_str_plz2(plz_input)

# 国家输入：为了兼容你两套表（DHL EU 是 country_code；Raben 用 country 名称）
# 这里做“方法2”：用户输入国家名/代码，我们自动转成两种格式
def normalize_country(user_text: str):
    s = (user_text or "").strip().lower()
    # 返回 (dhl_country_code, raben_country_name)
    mapping = {
        "de": ("DE", "Deutschland"),
        "deutschland": ("DE", "Deutschland"),
        "germany": ("DE", "Deutschland"),
        "德国": ("DE", "Deutschland"),

        "pl": ("PL", "Polen"),
        "polen": ("PL", "Polen"),
        "poland": ("PL", "Polen"),
        "波兰": ("PL", "Polen"),

        "bg": ("BG", "Bulgarien"),
        "bulgarien": ("BG", "Bulgarien"),
        "bulgaria": ("BG", "Bulgarien"),
        "保加利亚": ("BG", "Bulgarien"),

        "lv": ("LV", "Lettland"),
        "lettland": ("LV", "Lettland"),
        "latvia": ("LV", "Lettland"),
        "拉脱维亚": ("LV", "Lettland"),
    }
    return mapping.get(s, ("", ""))

# DE 默认德国；EU 默认波兰
default_country_text = "Deutschland" if scope == "DE" else "Polen"
country_input = st.text_input("Destination Country（可输入：Polen/PL/波兰 等）", value=default_country_text)
dhl_cc, raben_country = normalize_country(country_input)

if st.button("💰 计算报价"):
    st.header("📊 结果（Netto）")
    left, right = st.columns(2)

    # ===== DHL =====
    with left:
        st.subheader("DHL Freight")
        try:
            dhl_de_zone = read_csv_safe("dhl_de_plz2_zone.csv")
            dhl_de_rates = read_csv_safe("dhl_de_rates.csv")

            if scope == "DE":
                zone = pick_zone_de(dhl_de_zone, plz2)
                if zone is None:
                    st.error("DHL：无法匹配分区（检查 dhl_de_plz2_zone.csv 是否包含该 PLZ 前2位）")
                else:
                    base = pick_rate(dhl_de_rates, zone, weight)
                    if base is None:
                        st.error("DHL：无法匹配重量段（检查 dhl_de_rates.csv 的重量段）")
                    else:
                        total = base * (1.0 + float(dhl_fuel))
                        st.success(f"Zone {zone} | Base €{base:.2f} | Fuel {dhl_fuel:.2%} | Total €{total:.2f}")
            else:
                # EU：用 dhl_eu_zone_map.csv + dhl_eu_rates_long.csv
                dhl_eu_zone = read_csv_safe("dhl_eu_zone_map.csv")
                dhl_eu_rates = read_csv_safe("dhl_eu_rates_long.csv")

                if not dhl_cc:
                    st.error("DHL：EU 需要国家代码（例如 PL / BG / LV）。你可以输入 Polen 或 PL。")
                else:
                    zone = pick_zone_eu(dhl_eu_zone, dhl_cc, plz2)
                    if zone is None:
                        st.error("DHL：无法匹配 EU 分区（检查 dhl_eu_zone_map.csv country_code+plz/ plz2）")
                    else:
                        base = pick_rate(dhl_eu_rates, zone, weight)
                        if base is None:
                            st.error("DHL：无法匹配 EU 重量段（检查 dhl_eu_rates_long.csv）")
                        else:
                            total = base * (1.0 + float(dhl_fuel))
                            st.success(f"{dhl_cc}-{plz2} Zone {zone} | Base €{base:.2f} | Fuel {dhl_fuel:.2%} | Total €{total:.2f}")

        except Exception as e:
            st.error(f"DHL 系统错误：{e}")

    # ===== Raben =====
    with right:
        st.subheader("Raben")
        try:
            raben_zone = read_csv_safe("raben_zone_map.csv")
            raben_rates = read_csv_safe("raben_rates_long.csv")

            # 你的 raben 表头：scope,country,plz,zone 以及 scope,country,zone,w_from,w_to,price
            # 这里做兼容：plz 或 plz2 都能认
            raben_zone = ensure_col(raben_zone, ["plz2"], "plz")
            raben_rates = ensure_col(raben_rates, ["wfrom"], "w_from")
            raben_rates = ensure_col(raben_rates, ["wto"], "w_to")

            if not raben_country:
                st.error("Raben：请输入国家（例如 Deutschland/德国/DE 或 Polen/波兰/PL）")
            else:
                z = raben_zone[
                    (raben_zone["scope"].astype(str).str.strip() == scope) &
                    (raben_zone["country"].astype(str).str.strip() == raben_country) &
                    (raben_zone["plz"].astype(str).str.zfill(2) == plz2)
                ]
                if z.empty:
                    st.error("Raben：无法匹配分区（检查 raben_zone_map.csv 的 scope/country/plz）")
                else:
                    zone = int(z.iloc[0]["zone"])
                    r = raben_rates[
                        (raben_rates["scope"].astype(str).str.strip() == scope) &
                        (raben_rates["country"].astype(str).str.strip() == raben_country) &
                        (raben_rates["zone"].astype(int) == zone) &
                        (raben_rates["w_from"].astype(float) <= float(weight)) &
                        (raben_rates["w_to"].astype(float) >= float(weight))
                    ]
                    if r.empty:
                        st.error("Raben：无法匹配重量段（检查 raben_rates_long.csv 的 w_from/w_to）")
                    else:
                        base = float(r.iloc[0]["price"])
                        total = base * (1.0 + float(raben_daf))
                        st.success(f"{raben_country} Zone {zone} | Base €{base:.2f} | DAF {raben_daf:.2%} | Total €{total:.2f}")

        except Exception as e:
            st.error(f"Raben 系统错误：{e}")

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st


# =========================
# 基础配置
# =========================
st.set_page_config(
    page_title="Aifuge 双承运商报价系统（生产版）",
    page_icon="🚚",
    layout="wide",
)

DATA_DIR = Path("data")

FILES = {
    "params": DATA_DIR / "params_default.json",
    "dhl_de_plz2_zone": DATA_DIR / "dhl_de_plz2_zone.csv",
    "dhl_de_rates": DATA_DIR / "dhl_de_rates.csv",
    "dhl_eu_zone_map": DATA_DIR / "dhl_eu_zone_map.csv",
    "dhl_eu_rates_long": DATA_DIR / "dhl_eu_rates_long.csv",
    "raben_zone_map": DATA_DIR / "raben_zone_map.csv",
    "raben_rates_long": DATA_DIR / "raben_rates_long.csv",
}


# =========================
# 工具函数
# =========================
def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        # 兼容一些csv分隔符/编码问题
        try:
            return pd.read_csv(path, sep=";")
        except Exception:
            return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_all_data():
    params = {}
    if FILES["params"].exists():
        try:
            params = json.loads(FILES["params"].read_text(encoding="utf-8"))
        except Exception:
            params = {}

    dhl_de_plz2_zone = _safe_read_csv(FILES["dhl_de_plz2_zone"])
    dhl_de_rates = _safe_read_csv(FILES["dhl_de_rates"])
    dhl_eu_zone_map = _safe_read_csv(FILES["dhl_eu_zone_map"])
    dhl_eu_rates_long = _safe_read_csv(FILES["dhl_eu_rates_long"])
    raben_zone_map = _safe_read_csv(FILES["raben_zone_map"])
    raben_rates_long = _safe_read_csv(FILES["raben_rates_long"])

    return (
        params,
        dhl_de_plz2_zone,
        dhl_de_rates,
        dhl_eu_zone_map,
        dhl_eu_rates_long,
        raben_zone_map,
        raben_rates_long,
    )


def normalize_plz2(x: str) -> str:
    """取前2位数字（允许用户输入 38110 / 38 / '44xxx'）"""
    s = str(x).strip()
    m = re.search(r"\d{2}", s)
    return m.group(0) if m else ""


def normalize_country_input(s: str):
    """
    把用户输入的国家（PL/Polen/Poland/Deutschland/Germany 等）统一成：
    - country_code: 'PL' / 'DE' / 'BG' / 'LV' ...
    - raben_country_name: 用于匹配 raben_zone_map / raben_rates_long 的 country 字段
    注意：你现有CSV里 Raben 使用的是 'Polen'/'Deutschland'/'Bulgarien'/'Lettland' 这种德语名
    """
    raw = (s or "").strip()
    u = raw.upper()

    mapping = {
        # 德国
        "DE": ("DE", "Deutschland"),
        "DEUTSCHLAND": ("DE", "Deutschland"),
        "GERMANY": ("DE", "Deutschland"),
        # 波兰
        "PL": ("PL", "Polen"),
        "POLEN": ("PL", "Polen"),
        "POLAND": ("PL", "Polen"),
        "POLSKA": ("PL", "Polen"),
        # 保加利亚
        "BG": ("BG", "Bulgarien"),
        "BULGARIA": ("BG", "Bulgarien"),
        "BULGARIEN": ("BG", "Bulgarien"),
        # 拉脱维亚
        "LV": ("LV", "Lettland"),
        "LATVIA": ("LV", "Lettland"),
        "LETTLAND": ("LV", "Lettland"),
    }

    key = u.replace(" ", "")
    if key in mapping:
        return mapping[key]

    # 如果用户直接输入了 Raben CSV 的 country（如 Polen/Deutschland），尽量推断
    # 否则就把 country_code 留空，但 raben_country_name 用原始输入
    if raw.lower() == "deutschland":
        return ("DE", "Deutschland")
    if raw.lower() == "polen":
        return ("PL", "Polen")

    return ("", raw)


def ensure_cols(df: pd.DataFrame, required: list[str], df_name: str):
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"{df_name} 表缺列: {missing}")


def find_price_by_weight(df_rates: pd.DataFrame, weight: float):
    """
    df_rates 必须有 w_from, w_to, price
    匹配逻辑：w_from <= weight <= w_to（包含边界）
    """
    ensure_cols(df_rates, ["w_from", "w_to", "price"], "rates")

    # 强制数值化
    tmp = df_rates.copy()
    tmp["w_from"] = pd.to_numeric(tmp["w_from"], errors="coerce")
    tmp["w_to"] = pd.to_numeric(tmp["w_to"], errors="coerce")
    tmp["price"] = pd.to_numeric(tmp["price"], errors="coerce")
    tmp = tmp.dropna(subset=["w_from", "w_to", "price"])

    if tmp.empty:
        return None, None, None, 0.0, 0.0

    w_min = float(tmp["w_from"].min())
    w_max = float(tmp["w_to"].max())

    row = tmp[(tmp["w_from"] <= weight) & (weight <= tmp["w_to"])].sort_values(["w_from", "w_to"]).head(1)
    if row.empty:
        return None, None, None, w_min, w_max

    r = row.iloc[0]
    return float(r["price"]), float(r["w_from"]), float(r["w_to"]), w_min, w_max


# =========================
# 载入数据
# =========================
(
    params,
    dhl_de_plz2_zone,
    dhl_de_rates,
    dhl_eu_zone_map,
    dhl_eu_rates_long,
    raben_zone_map,
    raben_rates_long,
) = load_all_data()


# =========================
# Sidebar 参数（管理员维护）
# =========================
st.sidebar.markdown("## ⚙️ 参数")

def _param_number(key: str, default: float, step: float = 0.01):
    v = params.get(key, default)
    return st.sidebar.number_input(key, value=float(v), step=step, format="%.4f")

dhl_fuel = _param_number("DHL Fuel %", 0.12, 0.01)
dhl_security = _param_number("DHL Sicherheitszuschlag %", 0.00, 0.01)
raben_daf = _param_number("Raben DAF %", 0.10, 0.01)
raben_mob = _param_number("Raben Mobilitäts-Floater %", 0.029, 0.001)
raben_adr_fee = _param_number("Raben ADR Fee €", 12.50, 0.5)
raben_avis_fee = _param_number("Raben Avis Fee €", 12.00, 0.5)
raben_ins_min = _param_number("Raben Insurance Min €", 5.95, 0.05)

with st.sidebar.expander("🔍 数据状态（排错用）", expanded=False):
    st.write("dhl_de_plz2_zone 行数:", len(dhl_de_plz2_zone))
    st.write("dhl_de_rates 行数:", len(dhl_de_rates))
    st.write("dhl_eu_zone_map 行数:", len(dhl_eu_zone_map))
    st.write("dhl_eu_rates_long 行数:", len(dhl_eu_rates_long))
    st.write("raben_zone_map 行数:", len(raben_zone_map))
    st.write("raben_rates_long 行数:", len(raben_rates_long))
    st.caption("如果行数很少/为0，说明CSV没提交成功或路径不对。")


# =========================
# 主界面
# =========================
st.title("🚚 Aifuge 双承运商报价系统（生产版）")
st.markdown("### 📦 输入")

c1, c2, c3 = st.columns([2.2, 2.0, 2.0], vertical_alignment="bottom")

with c1:
    scope = st.selectbox("Scope", ["DE", "EU"], index=0)
with c2:
    weight = st.number_input("Actual Weight (kg)", min_value=0.01, value=200.0, step=10.0, format="%.2f")
with c3:
    plz2 = st.text_input("Destination PLZ (前2位)", value="38")

dest_country_raw = st.text_input("Destination Country（可输入：Polen/PL/波兰等）", value="Deutschland")

adr = st.checkbox("ADR（危险品）", value=False)
avis = st.checkbox("Avis 预约/派送", value=False)
insurance_value = st.number_input("Insurance Value €（可选）", min_value=0.0, value=0.0, step=100.0, format="%.2f")

btn = st.button("💰 计算报价", type="primary")


# =========================
# 计算逻辑
# =========================
def calc_dhl(scope: str, country_code: str, plz2: str, weight: float):
    """
    DHL:
    - scope=DE: plz2->zone via dhl_de_plz2_zone, rates via dhl_de_rates
    - scope=EU: (country_code,plz2)->zone via dhl_eu_zone_map, rates via dhl_eu_rates_long
    """
    plz2n = normalize_plz2(plz2)
    if not plz2n:
        return None, "DHL：PLZ 前2位无法识别（请输入例如 38 或 38110）"

    if scope == "DE":
        if dhl_de_plz2_zone.empty or dhl_de_rates.empty:
            return None, "DHL：缺少 DE 数据文件（dhl_de_plz2_zone.csv / dhl_de_rates.csv）"

        ensure_cols(dhl_de_plz2_zone, ["plz2", "zone"], "dhl_de_plz2_zone")
        ensure_cols(dhl_de_rates, ["zone", "w_from", "w_to", "price"], "dhl_de_rates")

        zrow = dhl_de_plz2_zone[dhl_de_plz2_zone["plz2"].astype(str) == str(plz2n)]
        if zrow.empty:
            return None, f"DHL：找不到 DE 的 PLZ2={plz2n} 对应 zone（检查 dhl_de_plz2_zone.csv）"
        zone = int(zrow.iloc[0]["zone"])

        rates = dhl_de_rates[dhl_de_rates["zone"].astype(int) == zone]
        base, w_from, w_to, w_min, w_max = find_price_by_weight(rates, weight)
        if base is None:
            return None, f"DHL：无法匹配重量段（你当前CSV最大到 {w_max:.0f}kg）。需要把 DHL DE rates 补到更大重量段。"

        fuel_amt = base * float(dhl_fuel)
        sec_amt = base * float(dhl_security)
        total = base + fuel_amt + sec_amt

        return {
            "zone": zone,
            "base": base,
            "fuel_amt": fuel_amt,
            "sec_amt": sec_amt,
            "total": total,
            "bracket": (w_from, w_to),
            "plz2": plz2n,
        }, None

    # EU
    if not country_code:
        return None, "DHL：EU 模式下需要可识别的国家（例如 Polen/PL/Poland）"

    if dhl_eu_zone_map.empty or dhl_eu_rates_long.empty:
        return None, "DHL：缺少 EU 数据文件（dhl_eu_zone_map.csv / dhl_eu_rates_long.csv）"

    ensure_cols(dhl_eu_zone_map, ["country_code", "plz2", "zone"], "dhl_eu_zone_map")
    ensure_cols(dhl_eu_rates_long, ["country_code", "zone", "w_from", "w_to", "price"], "dhl_eu_rates_long")

    zrow = dhl_eu_zone_map[
        (dhl_eu_zone_map["country_code"].astype(str).str.upper() == country_code.upper())
        & (dhl_eu_zone_map["plz2"].astype(str) == str(plz2n))
    ]
    if zrow.empty:
        return None, f"DHL：找不到 EU 的 {country_code}-{plz2n} 对应 zone（检查 dhl_eu_zone_map.csv）"
    zone = int(zrow.iloc[0]["zone"])

    rates = dhl_eu_rates_long[
        (dhl_eu_rates_long["country_code"].astype(str).str.upper() == country_code.upper())
        & (dhl_eu_rates_long["zone"].astype(int) == zone)
    ]
    base, w_from, w_to, w_min, w_max = find_price_by_weight(rates, weight)
    if base is None:
        return None, f"DHL：无法匹配 EU 重量段（你当前CSV最大到 {w_max:.0f}kg）。需要把 dhl_eu_rates_long.csv 补到更大重量段。"

    fuel_amt = base * float(dhl_fuel)
    sec_amt = base * float(dhl_security)
    total = base + fuel_amt + sec_amt

    return {
        "zone": zone,
        "base": base,
        "fuel_amt": fuel_amt,
        "sec_amt": sec_amt,
        "total": total,
        "bracket": (w_from, w_to),
        "plz2": plz2n,
        "country_code": country_code.upper(),
    }, None


def calc_raben(scope: str, raben_country: str, plz2: str, weight: float, adr: bool, avis: bool, insurance_value: float):
    """
    Raben:
    - zone map: raben_zone_map(scope,country,plz2,zone)
    - rates: raben_rates_long(scope,country,zone,w_from,w_to,price)
    """
    plz2n = normalize_plz2(plz2)
    if not plz2n:
        return None, "Raben：PLZ 前2位无法识别（请输入例如 44 或 4490）"

    if raben_zone_map.empty or raben_rates_long.empty:
        return None, "Raben：缺少数据文件（raben_zone_map.csv / raben_rates_long.csv）"

    ensure_cols(raben_zone_map, ["scope", "country", "plz2", "zone"], "raben_zone_map")
    ensure_cols(raben_rates_long, ["scope", "country", "zone", "w_from", "w_to", "price"], "raben_rates_long")

    zrow = raben_zone_map[
        (raben_zone_map["scope"].astype(str).str.upper() == scope.upper())
        & (raben_zone_map["country"].astype(str).str.lower() == str(raben_country).lower())
        & (raben_zone_map["plz2"].astype(str) == str(plz2n))
    ]
    if zrow.empty:
        return None, f"Raben：找不到 {scope}-{raben_country}-{plz2n} zone（检查 raben_zone_map.csv）"
    zone = int(zrow.iloc[0]["zone"])

    rates = raben_rates_long[
        (raben_rates_long["scope"].astype(str).str.upper() == scope.upper())
        & (raben_rates_long["country"].astype(str).str.lower() == str(raben_country).lower())
        & (raben_rates_long["zone"].astype(int) == zone)
    ]
    base, w_from, w_to, w_min, w_max = find_price_by_weight(rates, weight)
    if base is None:
        return None, f"Raben：无法匹配重量段（你当前CSV最大到 {w_max:.0f}kg）。需要把 raben_rates_long.csv 补到更大重量段。"

    # DAF + Mobilitäts-Floater（你侧边栏写的是 DAF%，我这里按“DAF% + Mobilitäts%”都叠加在 base 上）
    daf_amt = base * float(raben_daf)
    mob_amt = base * float(raben_mob)

    adr_amt = float(raben_adr_fee) if adr else 0.0
    avis_amt = float(raben_avis_fee) if avis else 0.0

    # 保险：示例逻辑：如果填写了保险价值，则至少收 min
    ins_amt = 0.0
    if insurance_value and insurance_value > 0:
        ins_amt = float(raben_ins_min)

    total = base + daf_amt + mob_amt + adr_amt + avis_amt + ins_amt

    return {
        "zone": zone,
        "base": base,
        "daf_amt": daf_amt,
        "mob_amt": mob_amt,
        "adr_amt": adr_amt,
        "avis_amt": avis_amt,
        "ins_amt": ins_amt,
        "total": total,
        "bracket": (w_from, w_to),
        "plz2": plz2n,
        "country": raben_country,
        "scope": scope,
    }, None


# =========================
# 输出
# =========================
if btn:
    country_code, raben_country = normalize_country_input(dest_country_raw)
    plz2n = normalize_plz2(plz2)

    st.markdown("---")
    st.markdown("## 📊 结果（Netto）")

    left, right = st.columns(2)

    # DHL
    with left:
        st.subheader("DHL Freight")
        try:
            dhl_res, dhl_err = calc_dhl(scope, country_code, plz2n, float(weight))
            if dhl_err:
                st.error(dhl_err)
            else:
                w_from, w_to = dhl_res["bracket"]
                st.success(
                    f"Zone {dhl_res['zone']} | "
                    f"Weight {weight:.0f}kg in [{w_from:.0f}-{w_to:.0f}] | "
                    f"Base €{dhl_res['base']:.2f} | "
                    f"Fuel {float(dhl_fuel)*100:.2f}% (€{dhl_res['fuel_amt']:.2f}) | "
                    f"Security {float(dhl_security)*100:.2f}% (€{dhl_res['sec_amt']:.2f}) | "
                    f"Total €{dhl_res['total']:.2f}"
                )
        except KeyError as e:
            st.error(f"DHL 系统错误：{e}")
        except Exception as e:
            st.error(f"DHL 系统错误：{e}")

    # Raben
    with right:
        st.subheader("Raben")
        try:
            raben_res, raben_err = calc_raben(scope, raben_country, plz2n, float(weight), adr, avis, float(insurance_value))
            if raben_err:
                st.error(raben_err)
            else:
                w_from, w_to = raben_res["bracket"]
                st.success(
                    f"{raben_res['country']} Zone {raben_res['zone']} | "
                    f"Weight {weight:.0f}kg in [{w_from:.0f}-{w_to:.0f}] | "
                    f"Base €{raben_res['base']:.2f} | "
                    f"DAF {float(raben_daf)*100:.2f}% (€{raben_res['daf_amt']:.2f}) | "
                    f"Mob {float(raben_mob)*100:.2f}% (€{raben_res['mob_amt']:.2f}) | "
                    f"ADR €{raben_res['adr_amt']:.2f} | Avis €{raben_res['avis_amt']:.2f} | Ins €{raben_res['ins_amt']:.2f} | "
                    f"Total €{raben_res['total']:.2f}"
                )
        except KeyError as e:
            st.error(f"Raben 系统错误：{e}")
        except Exception as e:
            st.error(f"Raben 系统错误：{e}")

    st.caption(
        "提示：如果你输入 2000kg/5000kg 仍然提示“无法匹配重量段”，那不是程序问题，而是你的 CSV 还没补全到对应重量范围。"
    )

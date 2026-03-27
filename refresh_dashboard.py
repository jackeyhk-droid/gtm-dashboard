#!/usr/bin/env python3
"""
GTM Dashboard — Automated FRED Data Refresh Script
====================================================
Pulls latest data from FRED API, calculates Net Liquidity & derived indicators,
and updates gtm-dashboard.html with fresh numbers.

Usage:
  python refresh_dashboard.py                    # Uses FRED_API_KEY env var
  FRED_API_KEY=xxxxx python refresh_dashboard.py # Explicit key

Runs automatically via GitHub Actions every Thursday night (US Eastern).
Can also be run locally for testing.
"""

import os
import sys
import json
import re
import math
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

API_KEY = os.environ.get("FRED_API_KEY", "")
if not API_KEY:
    print("ERROR: FRED_API_KEY environment variable not set.")
    print("Set it with: export FRED_API_KEY=your_key_here")
    sys.exit(1)

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
HTML_FILE = "index.html"

# ═══════════════════════════════════════════════════════════════
# FRED API HELPERS
# ═══════════════════════════════════════════════════════════════

def fetch_fred(series_id, limit=1, units=None, frequency=None, start=None, sort="desc"):
    """Fetch observations from FRED API."""
    params = {
        "series_id": series_id,
        "api_key": API_KEY,
        "file_type": "json",
        "sort_order": sort,
        "limit": limit,
    }
    if units:
        params["units"] = units
    if frequency:
        params["frequency"] = frequency
    if start:
        params["observation_start"] = start

    try:
        resp = requests.get(BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        obs = data.get("observations", [])
        return [(o["date"], float(o["value"])) for o in obs if o["value"] != "."]
    except Exception as e:
        print(f"  WARNING: Failed to fetch {series_id}: {e}")
        return []


def latest(series_id, units=None):
    """Get the single latest value for a FRED series."""
    data = fetch_fred(series_id, limit=1, units=units)
    if data:
        print(f"  {series_id}: {data[0][1]} ({data[0][0]})")
        return data[0]  # (date, value)
    return (None, None)

# ═══════════════════════════════════════════════════════════════
# STEP 1: PULL ALL FRED DATA
# ═══════════════════════════════════════════════════════════════

def pull_fred_data():
    """Pull all 35+ FRED series and return as a dict."""
    print("\n═══ PULLING FRED DATA ═══")
    d = {}

    # Rates
    print("\n--- Rates ---")
    d["DFF"] = latest("DFF")
    d["DGS2"] = latest("DGS2")
    d["DGS5"] = latest("DGS5")
    d["DGS10"] = latest("DGS10")
    d["DGS30"] = latest("DGS30")
    d["DFII10"] = latest("DFII10")
    d["T10YIE"] = latest("T10YIE")
    d["T10Y3M"] = latest("T10Y3M")
    d["MORTGAGE30US"] = latest("MORTGAGE30US")

    # Credit
    print("\n--- Credit Spreads ---")
    d["BAMLC0A0CM"] = latest("BAMLC0A0CM")    # IG OAS (%)
    d["BAMLH0A0HYM2"] = latest("BAMLH0A0HYM2")  # HY OAS (%)

    # Equity & Vol
    print("\n--- Equity & Volatility ---")
    d["SP500"] = latest("SP500")
    d["VIXCLS"] = latest("VIXCLS")

    # Inflation (YoY)
    print("\n--- Inflation ---")
    d["CPIAUCSL"] = latest("CPIAUCSL", units="pc1")
    d["CPILFESL"] = latest("CPILFESL", units="pc1")
    d["PCEPI"] = latest("PCEPI", units="pc1")
    d["PCEPILFE"] = latest("PCEPILFE", units="pc1")

    # Labor
    print("\n--- Labor Market ---")
    d["UNRATE"] = latest("UNRATE")
    d["PAYEMS"] = latest("PAYEMS", units="chg")
    d["CES0500000003"] = latest("CES0500000003")
    d["JTSJOL"] = latest("JTSJOL")
    d["JTSHIL"] = latest("JTSHIL")
    d["JTSLDL"] = latest("JTSLDL")
    d["ICSA"] = latest("ICSA")

    # Consumer
    print("\n--- Consumer & Sentiment ---")
    d["UMCSENT"] = latest("UMCSENT")
    d["TDSP"] = latest("TDSP")
    d["DRCCLACBS"] = latest("DRCCLACBS")

    # Dollar
    print("\n--- Dollar ---")
    d["DTWEXBGS"] = latest("DTWEXBGS")

    # Money Market
    print("\n--- Money Market (SOFR/IORB) ---")
    d["SOFR"] = latest("SOFR")
    d["IORB"] = latest("IORB")

    return d

# ═══════════════════════════════════════════════════════════════
# STEP 2: NET LIQUIDITY CALCULATION
# ═══════════════════════════════════════════════════════════════

def pull_nl_data():
    """Pull NL components and compute Net Liquidity with full history."""
    print("\n═══ NET LIQUIDITY CALCULATION ═══")

    # WALCL is the anchor — publishes weekly on Wednesdays
    walcl = fetch_fred("WALCL", limit=1)
    if not walcl:
        print("ERROR: Could not fetch WALCL")
        return None

    anchor_date = walcl[0][0]  # e.g. "2026-03-18" (Wednesday)
    w_val = walcl[0][1]

    # Align TGA and RRP to the WALCL Wednesday anchor date
    # Pull recent daily data, then find the value on or before anchor_date
    tga_recent = fetch_fred("WTREGEN", limit=10, sort="desc")
    rrp_recent = fetch_fred("RRPONTSYD", limit=10, sort="desc")

    t_val = None
    for date, val in tga_recent:
        if date <= anchor_date:
            t_val = val
            print(f"  TGA aligned: {date} → {val:,.0f}M")
            break

    r_val = None
    for date, val in rrp_recent:
        if date <= anchor_date:
            r_val = val
            print(f"  RRP aligned: {date} → {val}B")
            break

    if t_val is None or r_val is None:
        print("ERROR: Could not align TGA/RRP to WALCL anchor date")
        return None

    r_val_m = r_val * 1000  # Billions → Millions

    nl_m = w_val - t_val - r_val_m
    nl_t = nl_m / 1_000_000

    print(f"  WALCL:  {w_val:,.0f}M  (${w_val/1e6:.3f}T)  [{anchor_date}]")
    print(f"  TGA:    {t_val:,.0f}M  (${t_val/1e6:.3f}T)")
    print(f"  RRP:    {r_val:.1f}B → {r_val_m:,.0f}M")
    print(f"  NL:     {nl_m:,.0f}M  (${nl_t:.3f}T)")
    print(f"  Anchor: {anchor_date} (WALCL Wednesday)")

    # History for chart (monthly sampling, weekly for last year)
    print("\n--- Building NL history for chart ---")
    walcl_hist = fetch_fred("WALCL", limit=600, start="2015-01-01", sort="asc")
    tga_hist = fetch_fred("WTREGEN", limit=600, start="2015-01-01", sort="asc")
    rrp_hist = fetch_fred("RRPONTSYD", limit=4000, start="2015-01-01", sort="asc")
    sp_hist = fetch_fred("SP500", limit=4000, start="2015-01-01", sort="asc")

    # Build lookup maps for alignment
    tga_map = {d: v for d, v in tga_hist}
    rrp_map = {d: v for d, v in rrp_hist}
    sp_map = {d: v for d, v in sp_hist}

    def find_nearest(data_map, target_date, max_days=5):
        """Find value on or before target_date within max_days."""
        from datetime import datetime, timedelta
        td = datetime.strptime(target_date, "%Y-%m-%d")
        for offset in range(max_days + 1):
            key = (td - timedelta(days=offset)).strftime("%Y-%m-%d")
            if key in data_map:
                return data_map[key]
        return None

    # Calculate NL for each WALCL Wednesday
    nl_history = []
    for date, w in walcl_hist:
        t = find_nearest(tga_map, date)
        r = find_nearest(rrp_map, date)
        s = find_nearest(sp_map, date)
        if t is not None and r is not None and s is not None:
            nl = (w - t - r * 1000) / 1_000_000  # T
            nl_history.append({
                "date": date,
                "label": f"{date[2:4]}/{date[5:7]}",
                "nl": round(nl, 2),
                "sp": round(s, 0),
            })

    # Keep ALL weekly points — no sampling, maximum accuracy
    sampled = nl_history

    print(f"  NL history: {len(sampled)} points ({sampled[0]['date']} to {sampled[-1]['date']})")

    return {
        "walcl": w_val,
        "tga": t_val,
        "rrp_m": r_val_m,
        "rrp_b": r_val,
        "nl_m": nl_m,
        "nl_t": nl_t,
        "date": walcl[0][0],
        "history": sampled,
    }

# ═══════════════════════════════════════════════════════════════
# STEP 3: SOFR-IORB SPREAD HISTORY
# ═══════════════════════════════════════════════════════════════

def pull_sofr_spread():
    """Pull SOFR and IORB history, calculate spread."""
    print("\n═══ SOFR-IORB SPREAD ═══")
    sofr_hist = fetch_fred("SOFR", limit=300, frequency="w", start="2021-01-01", sort="asc")
    iorb_hist = fetch_fred("IORB", limit=300, frequency="w", start="2021-01-01", sort="asc")

    iorb_map = {d: v for d, v in iorb_hist}
    spread_data = []
    for date, sofr_val in sofr_hist:
        if date in iorb_map:
            spread_bps = round((sofr_val - iorb_map[date]) * 100, 1)
            spread_data.append({
                "date": date,
                "label": f"{date[2:4]}/{date[5:7]}",
                "spread": spread_bps,
            })

    # Sample monthly
    monthly = {}
    for item in spread_data:
        monthly[item["label"]] = item
    sampled = list(monthly.values())

    print(f"  Spread history: {len(sampled)} monthly points")
    if sampled:
        print(f"  Latest: {sampled[-1]['date']} = {sampled[-1]['spread']} bps")

    return sampled

# ═══════════════════════════════════════════════════════════════
# STEP 4: NL/SPX RATIO
# ═══════════════════════════════════════════════════════════════

def calc_nlspx_ratio(nl_history):
    """Calculate NL($B)/SPX ratio from history."""
    print("\n═══ NL/SPX RATIO ═══")
    # Sample from NL history (monthly)
    monthly = {}
    for item in nl_history:
        monthly[item["label"]] = item
    sampled = list(monthly.values())

    ratios = []
    for item in sampled:
        ratio = round((item["nl"] * 1000) / item["sp"], 2)
        ratios.append({"label": item["label"], "ratio": ratio})

    # Stats (sample stddev)
    vals = [r["ratio"] for r in ratios]
    n = len(vals)
    mean = sum(vals) / n
    sq_sum = sum((v - mean) ** 2 for v in vals)
    std = math.sqrt(sq_sum / (n - 1))
    warn = mean - std
    current = vals[-1]

    print(f"  Points: {n}")
    print(f"  Mean: {mean:.2f}, StdDev: {std:.2f}, -1σ: {warn:.2f}")
    print(f"  Current: {current} ({'BELOW -1σ!' if current < warn else 'OK'})")

    return {
        "data": ratios,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "warn": round(warn, 2),
        "current": current,
    }

# ═══════════════════════════════════════════════════════════════
# STEP 5: CPI HISTORY FOR CHART
# ═══════════════════════════════════════════════════════════════

def pull_cpi_history():
    """Pull recent CPI and Core CPI for the chart."""
    print("\n═══ CPI HISTORY ═══")
    cpi = fetch_fred("CPIAUCSL", limit=12, units="pc1", frequency="m", sort="asc",
                     start=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    core = fetch_fred("CPILFESL", limit=12, units="pc1", frequency="m", sort="asc",
                      start=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))

    # Align and format
    core_map = {d: v for d, v in core}
    history = []
    for date, val in cpi[-12:]:
        dt = datetime.strptime(date, "%Y-%m-%d")
        label = dt.strftime("%b'%y").replace("'0", "'").replace("'2", "'2")
        # Simpler label: "Mar25", "Apr25", etc
        label = f"{dt.strftime('%b')}{dt.strftime('%y')}"
        c_val = core_map.get(date, None)
        if c_val is not None:
            history.append({"label": label, "cpi": round(val, 2), "core": round(c_val, 2)})

    print(f"  CPI history: {len(history)} months")
    return history

# ═══════════════════════════════════════════════════════════════
# STEP 6: NFP RECENT HISTORY
# ═══════════════════════════════════════════════════════════════

def pull_nfp_history():
    """Pull recent NFP prints."""
    print("\n═══ NFP HISTORY ═══")
    data = fetch_fred("PAYEMS", limit=6, units="chg", frequency="m", sort="desc")
    data.reverse()
    nfp = []
    for date, val in data[-5:]:
        dt = datetime.strptime(date, "%Y-%m-%d")
        label = f"{dt.strftime('%b')}{dt.strftime('%y')}"
        nfp.append({"label": label, "value": round(val, 0)})
        print(f"  {label}: {val:+.0f}K")
    return nfp

# ═══════════════════════════════════════════════════════════════
# STEP 7: UPDATE HTML FILE
# ═══════════════════════════════════════════════════════════════

def update_html(fred, nl, sofr_spread, nlspx, cpi_hist, nfp_hist):
    """Read the HTML file and update all data sections."""
    print(f"\n═══ UPDATING {HTML_FILE} ═══")

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    today = datetime.now().strftime("%b %d, %Y")
    nl_date = nl["date"]  # e.g. "2026-03-25"
    nl_date_fmt = datetime.strptime(nl_date, "%Y-%m-%d").strftime("%b %d, %Y")

    # --- Helper: replace text between markers ---
    def replace_val(pattern, new_val):
        nonlocal html
        count = 0
        while pattern in html:
            html = html.replace(pattern, new_val, 1)
            count += 1
        return count

    # ═══ A. UPDATE HEADER DATE ═══
    html = re.sub(
        r'(FRED API \+ JPM GTM PDF \| )\w+ \d+, \d{4}',
        f'\\g<1>{today}',
        html
    )

    # ═══ B. UPDATE HEADER PILLS ═══
    sp_val = fred["SP500"][1]
    vix_val = fred["VIXCLS"][1]
    y10_val = fred["DGS10"][1]

    html = re.sub(r'S&amp;P [\d,]+', f'S&amp;P {sp_val:,.0f}', html)
    html = re.sub(r'(pill[^>]*>)S&P [\d,]+', f'\\g<1>S&P {sp_val:,.0f}', html)
    html = re.sub(r'(pill[^>]*>)10Y [\d.]+%', f'\\g<1>10Y {y10_val:.1f}%', html)
    html = re.sub(r'(pill[^>]*>)NL \$[\d.]+T', f'\\g<1>NL ${nl["nl_t"]:.1f}T', html)
    html = re.sub(r'(pill[^>]*>)VIX [\d.]+', f'\\g<1>VIX {vix_val:.1f}', html)

    # ═══ C. UPDATE NL DATA ARRAY (for chart) ═══
    nl_js_items = []
    for item in nl["history"]:
        nl_js_items.append(f"{{d:'{item['label']}',n:{item['nl']},s:{int(item['sp'])}}}")

    nl_js = "var nlData = [\n  " + ",".join(nl_js_items) + "\n];"
    html = re.sub(r'var nlData = \[[\s\S]*?\];', nl_js, html)

    # ═══ D. UPDATE SOFR SPREAD ARRAY ═══
    sofr_labels = [s["label"] for s in sofr_spread]
    sofr_vals = [s["spread"] for s in sofr_spread]
    html = re.sub(
        r"var sofrLabels = \[.*?\];",
        "var sofrLabels = [" + ",".join(f"'{l}'" for l in sofr_labels) + "];",
        html
    )
    html = re.sub(
        r"var sofrSpread = \[.*?\];",
        "var sofrSpread = [" + ",".join(str(v) for v in sofr_vals) + "];",
        html
    )

    # ═══ E. UPDATE NL/SPX RATIO ARRAYS ═══
    nlspx_labels = [r["label"] for r in nlspx["data"]]
    nlspx_vals = [r["ratio"] for r in nlspx["data"]]
    html = re.sub(
        r"var nlspxLabels = \[.*?\];",
        "var nlspxLabels = [" + ",".join(f"'{l}'" for l in nlspx_labels) + "];",
        html
    )
    html = re.sub(
        r"var nlspxVals = \[.*?\];",
        "var nlspxVals = [" + ",".join(str(v) for v in nlspx_vals) + "];",
        html
    )

    # ═══ F. UPDATE NFP ARRAY ═══
    nfp_labels = [n["label"] for n in nfp_hist]
    nfp_vals = [int(n["value"]) for n in nfp_hist]
    html = re.sub(
        r"labels:\['[A-Z][a-z]+\d+'.*?\], datasets:\[\{ data:nfpVals",
        f"labels:[" + ",".join(f"'{l}'" for l in nfp_labels) + "], datasets:[{ data:nfpVals",
        html
    )
    html = re.sub(
        r"var nfpVals = \[.*?\];",
        "var nfpVals = [" + ",".join(str(v) for v in nfp_vals) + "];",
        html
    )

    # ═══ G. UPDATE CPI CHART DATA ═══
    cpi_labels = [c["label"] for c in cpi_hist]
    cpi_vals = [c["cpi"] for c in cpi_hist]
    core_vals = [c["core"] for c in cpi_hist]

    # Replace CPI chart labels and data within the makeChart call
    html = re.sub(
        r"(makeChart\('c-cpi'.*?labels:\[)[^\]]+(\])",
        "\\g<1>" + ",".join(f"'{l}'" for l in cpi_labels) + "\\g<2>",
        html,
        flags=re.DOTALL
    )
    html = re.sub(
        r"(label:'CPI'.*?data:\[)[^\]]+(\])",
        "\\g<1>" + ",".join(str(v) for v in cpi_vals) + "\\g<2>",
        html
    )
    html = re.sub(
        r"(label:'Core'.*?data:\[)[^\]]+(\])",
        "\\g<1>" + ",".join(str(v) for v in core_vals) + "\\g<2>",
        html
    )

    # ═══ H. UPDATE KPI VALUES IN HTML ═══
    # This uses regex to find and replace specific KPI card values

    def update_kpi(label_text, new_value):
        """Update KPI value that follows a specific label."""
        nonlocal html
        pattern = f'({re.escape(label_text)}</div><div class="kpi-value">)[^<]+(</div>)'
        html = re.sub(pattern, f'\\g<1>{new_value}\\g<2>', html)

    # S&P 500
    update_kpi("S&P 500", f"{sp_val:,.0f}")
    # Update S&P date sub-label
    sp_date = datetime.strptime(fred["SP500"][0], "%Y-%m-%d").strftime("%b %d, %Y")
    html = re.sub(
        r'(S&P 500</div><div class="kpi-value">[^<]+</div><div class="kpi-sub">)[^<]+(</div>)',
        f'\\g<1>{sp_date}\\g<2>',
        html,
        count=1
    )

    # VIX
    update_kpi("VIX", f"{vix_val:.1f}")

    # Fed Funds
    ff = fred["DFF"][1]
    update_kpi("Fed Funds", f"{ff:.1f}%")

    # 10Y UST
    update_kpi("10Y UST", f"{y10_val:.1f}%")
    update_kpi("10Y", f"{y10_val:.1f}%")

    # 30Y
    y30 = fred["DGS30"][1]
    update_kpi("30Y", f"{y30:.1f}%")

    # Unemployment
    ur = fred["UNRATE"][1]
    nfp_latest = nfp_vals[-1] if nfp_vals else 0
    update_kpi("Unemployment", f"{ur:.1f}%")

    # CPI
    cpi_latest = fred["CPIAUCSL"][1]
    core_latest = fred["CPILFESL"][1]
    update_kpi("CPI YoY", f"{cpi_latest:.1f}%")
    update_kpi("CPI", f"{cpi_latest:.1f}%")

    # Net Liquidity
    update_kpi("Net Liquidity", f"${nl['nl_t']:.2f}T")

    # NL components
    update_kpi("WALCL", f"${nl['walcl']/1e6:.2f}T")
    update_kpi("TGA", f"${nl['tga']/1e6:.2f}T")
    update_kpi("ON RRP", f"${nl['rrp_m']:.0f}M")

    # Credit spreads
    ig = fred["BAMLC0A0CM"][1]
    hy = fred["BAMLH0A0HYM2"][1]
    ig_bps = round(ig * 100)
    hy_bps = round(hy * 100)
    update_kpi("IG / HY Spread", f"{ig_bps} / {hy_bps}")
    update_kpi("IG OAS", f"{ig_bps}bps")
    update_kpi("HY OAS", f"{hy_bps}bps")

    # SOFR / IORB
    sofr_val = fred["SOFR"][1]
    iorb_val = fred["IORB"][1]
    spread_bps = round((sofr_val - iorb_val) * 100)
    update_kpi("SOFR", f"{sofr_val:.2f}%")
    update_kpi("IORB", f"{iorb_val:.2f}%")

    # PCE
    pce = fred["PCEPI"][1]
    pce_core = fred["PCEPILFE"][1]
    update_kpi("PCE", f"{pce:.1f}%")

    # Sentiment
    sent = fred["UMCSENT"][1]
    update_kpi("Sentiment", f"{sent:.1f}")

    # Claims (ICSA returns actual number, convert to K)
    claims = fred["ICSA"][1]
    claims_k = claims / 1000 if claims > 1000 else claims
    update_kpi("Claims", f"{claims_k:.0f}K")

    # NFP
    update_kpi("NFP", f"{nfp_latest:+.0f}K")

    # ═══ I. UPDATE COMPONENT TABLE ═══
    html = re.sub(
        r'(WALCL \(Fed BS\)</td><td>)[\d,]+(</td><td>)\$[\d.]+T',
        f'\\g<1>{nl["walcl"]:,.0f}\\g<2>${nl["walcl"]/1e6:.3f}T',
        html
    )
    html = re.sub(
        r'(TGA Balance</td><td>)[\d,]+(</td><td>)\$[\d.]+T',
        f'\\g<1>{nl["tga"]:,.0f}\\g<2>${nl["tga"]/1e6:.3f}T',
        html
    )
    html = re.sub(
        r'(ON RRP</td><td>)[\d,]+(</td><td>)\$[\d.]+T',
        f'\\g<1>{nl["rrp_m"]:,.0f}\\g<2>${nl["rrp_m"]/1e6:.6f}T',
        html
    )
    html = re.sub(
        r'(Net Liquidity</td><td style="font-weight:700">)[\d,]+(</td><td style="font-weight:700">)\$[\d.]+T',
        f'\\g<1>{nl["nl_m"]:,.0f}\\g<2>${nl["nl_t"]:.3f}T',
        html
    )

    # ═══ J. UPDATE RATE DECOMPOSITION TABLE ═══
    rate_updates = {
        "Fed Funds": ("DFF", ""),
        "2-Year": ("DGS2", ""),
        "5-Year": ("DGS5", ""),
        "10-Year": ("DGS10", ""),
        "30-Year": ("DGS30", ""),
        "TIPS 10Y": ("DFII10", ""),
        "Breakeven": ("T10YIE", ""),
        "30Y Mortgage": ("MORTGAGE30US", ""),
    }
    for label, (series, _) in rate_updates.items():
        val = fred.get(series, (None, None))[1]
        if val is not None:
            html = re.sub(
                f'({re.escape(label)}</td><td>)[\\d.]+%',
                f'\\g<1>{val:.2f}%',
                html
            )

    # 10Y-3M spread
    slope = fred["T10Y3M"][1]
    slope_bps = round(slope * 100) if slope < 10 else round(slope)
    html = re.sub(
        r'(10Y-3M</td><td>)\d+bps',
        f'\\g<1>{slope_bps}bps',
        html
    )

    # ═══ K. UPDATE AS-OF TIMESTAMPS ═══
    html = re.sub(
        r'As of \w+ \d+, \d{4}',
        f'As of {today}',
        html
    )

    # NL component date
    nl_date_short = datetime.strptime(nl_date, "%Y-%m-%d").strftime("%b %d")
    html = re.sub(
        r'Components \(FRED API, \w+ \d+\)',
        f'Components (FRED API, {nl_date_short})',
        html
    )

    # ═══ L. AUTO-GENERATE WEEKLY SNAPSHOT ═══
    print("\n--- Generating Weekly Snapshot ---")

    # Gather all the data points we need
    nl_t = nl["nl_t"]
    rrp_m = nl["rrp_m"]
    tga_t = nl["tga"] / 1e6
    sofr_val = fred["SOFR"][1]
    iorb_val = fred["IORB"][1]
    sofr_iorb_bps = round((sofr_val - iorb_val) * 100)
    ur = fred["UNRATE"][1]
    nfp_latest = nfp_vals[-1] if nfp_vals else 0
    nfp_3mo_avg = round(sum(nfp_vals[-3:]) / min(len(nfp_vals), 3)) if nfp_vals else 0
    sent = fred["UMCSENT"][1]
    cpi_latest = fred["CPIAUCSL"][1]
    core_cpi = fred["CPILFESL"][1]
    pce = fred["PCEPI"][1]
    pce_core = fred["PCEPILFE"][1]
    ig_bps_v = round(fred["BAMLC0A0CM"][1] * 100)
    hy_bps_v = round(fred["BAMLH0A0HYM2"][1] * 100)
    slope_v = fred["T10Y3M"][1]
    slope_bps_v = round(slope_v * 100) if slope_v < 10 else round(slope_v)
    vix_v = fred["VIXCLS"][1]
    nlspx_current = nlspx["current"]
    nlspx_warn = nlspx["warn"]
    claims_v = fred["ICSA"][1]
    claims_k = claims_v / 1000 if claims_v > 1000 else claims_v
    nfp_month = nfp_hist[-1]["label"] if nfp_hist else "Latest"

    # --- Bullet 1 (gold): Net Liquidity status ---
    if nl_t >= 6.0:
        nl_zone = "Ample Reserve Zone (above $6.0T)"
        nl_risk = "Broadly supportive of risk assets."
    elif nl_t >= 5.5:
        nl_zone = "Inside the Transition Zone ($5.5-6.0T)"
        if rrp_m < 10000:  # RRP < $10B effectively depleted
            nl_risk = "RRP buffer depleted — TGA movements now drain NL dollar-for-dollar."
        else:
            nl_risk = f"RRP at ${rrp_m/1e6:.2f}T still provides some buffer."
    else:
        nl_zone = "Reserve Scarcity Zone (below $5.5T)"
        nl_risk = "High risk of funding stress and market volatility."

    bullet1 = f"Net Liquidity at ${nl_t:.2f}T &mdash; {nl_zone}. {nl_risk}"

    # --- Bullet 2 (red): Labor / growth signal ---
    if nfp_latest < 0:
        nfp_signal = f"{nfp_month} NFP printed {nfp_latest:+.0f}K"
    elif nfp_latest < 100:
        nfp_signal = f"{nfp_month} NFP soft at {nfp_latest:+.0f}K"
    else:
        nfp_signal = f"{nfp_month} NFP solid at {nfp_latest:+.0f}K"

    labor_parts = [nfp_signal, f"3-month average {nfp_3mo_avg:+.0f}K"]
    if ur >= 4.5:
        labor_parts.append(f"unemployment elevated at {ur:.1f}%")
    if sent < 65:
        labor_parts.append(f"UMich sentiment depressed at {sent:.1f} (long-run avg ~77)")
    elif sent < 75:
        labor_parts.append(f"UMich sentiment below average at {sent:.1f} (avg ~77)")

    if nfp_latest < 50 or ur >= 4.5:
        bullet2_prefix = "Labour market weakening"
    elif nfp_latest >= 200:
        bullet2_prefix = "Labour market resilient"
    else:
        bullet2_prefix = "Labour market mixed"

    bullet2 = f"{bullet2_prefix}: {'. '.join(labor_parts)}."

    # --- Bullet 3 (cyan): Rates / credit signal ---
    if slope_bps_v < 50:
        curve_signal = f"curve very flat at {slope_bps_v}bps (avg ~153)"
    elif slope_bps_v < 100:
        curve_signal = f"curve flat at {slope_bps_v}bps (avg ~153)"
    else:
        curve_signal = f"curve normalising at {slope_bps_v}bps (avg ~153)"

    if ig_bps_v < 100 and hy_bps_v < 400:
        spread_signal = f"Credit spreads tight (IG {ig_bps_v}bps, HY {hy_bps_v}bps) &mdash; limited cushion if conditions deteriorate"
    elif ig_bps_v < 150:
        spread_signal = f"Credit spreads near average (IG {ig_bps_v}bps, HY {hy_bps_v}bps)"
    else:
        spread_signal = f"Credit spreads widening (IG {ig_bps_v}bps, HY {hy_bps_v}bps) &mdash; stress building"

    if vix_v > 25:
        vol_note = f" VIX elevated at {vix_v:.1f}."
    elif vix_v > 20:
        vol_note = f" VIX moderately elevated at {vix_v:.1f}."
    else:
        vol_note = ""

    bullet3 = f"10Y at {y10_val:.1f}%, {curve_signal}. {spread_signal}.{vol_note}"

    # Build the HTML
    snapshot_html = (
        f'<span style="color:var(--gold);font-weight:600">&#9679;</span> {bullet1}<br>\n'
        f'      <span style="color:var(--red);font-weight:600">&#9679;</span> {bullet2}<br>\n'
        f'      <span style="color:var(--cyan);font-weight:600">&#9679;</span> {bullet3}'
    )

    # Replace existing snapshot content
    html = re.sub(
        r'(<div style="color:var\(--muted\)">\s*)<span style="color:var\(--gold\).*?</span>.*?(?=\s*</div>\s*</div>\s*<div class="kpi-row">)',
        f'\\g<1>{snapshot_html}\n    ',
        html,
        flags=re.DOTALL
    )
    print(f"  Bullet 1: {bullet1[:80]}...")
    print(f"  Bullet 2: {bullet2[:80]}...")
    print(f"  Bullet 3: {bullet3[:80]}...")

    # ═══ M. UPDATE NL ZONE NOTE ═══
    if nl_t >= 6.0:
        zone_note_text = f"${nl_t:.2f}T. Liquidity ample — supportive of risk assets."
        zone_note_color = "var(--green)"
        zone_note_bg = "rgba(0,230,138,0.08)"
    elif nl_t >= 5.5:
        zone_note_text = f"${nl_t:.2f}T. {nl_risk}"
        zone_note_color = "var(--gold)"
        zone_note_bg = "rgba(255,184,51,0.08)"
    else:
        zone_note_text = f"${nl_t:.2f}T. Reserve scarcity — elevated risk of funding stress."
        zone_note_color = "var(--red)"
        zone_note_bg = "rgba(255,77,106,0.08)"

    html = re.sub(
        r'(<div class="note" style="background:)rgba\([^)]+\)(;color:)var\(--\w+\)(">)\$[\d.]+T\.[^<]+',
        f'\\g<1>{zone_note_bg}\\g<2>{zone_note_color}\\g<3>{zone_note_text}',
        html,
        count=1
    )

    # ═══ N. UPDATE CARD SUBTITLES ═══
    # Yield curve subtitle
    html = re.sub(
        r'(10Y-3M: )\d+bps \(avg ~153bps\)',
        f'\\g<1>{slope_bps_v}bps (avg ~153bps)',
        html
    )
    html = re.sub(
        r'(10Y-3M at )\d+bps',
        f'\\g<1>{slope_bps_v}bps',
        html
    )
    # Slope in sub
    html = re.sub(
        r'(Slope: )\d+bps',
        f'\\g<1>{slope_bps_v}bps',
        html
    )

    # GDP subtitle — keep as-is (quarterly, not weekly)

    # CPI subtitle
    html = re.sub(
        r'(Headline )[\d.]+% \| Core [\d.]+%',
        f'\\g<1>{cpi_latest:.1f}% | Core {core_cpi:.1f}%',
        html
    )

    # NFP subtitle (3mo avg)
    html = re.sub(
        r'3mo avg: [+-]?\d+K',
        f'3mo avg: {nfp_3mo_avg:+.0f}K' if nfp_3mo_avg != 0 else f'3mo avg: {nfp_3mo_avg:.0f}K',
        html
    )

    # 10Y Real / BE in KPI sub
    tips_val = fred["DFII10"][1]
    be_val = fred["T10YIE"][1]
    html = re.sub(
        r'Real [\d.]+% \| BE [\d.]+%',
        f'Real {tips_val:.1f}% | BE {be_val:.1f}%',
        html
    )

    # NFP value in KPI sub (under Unemployment)
    html = re.sub(
        r'(Unemployment.*?kpi-sub[^>]*>)NFP [+-]?\d+K',
        f'\\g<1>NFP {nfp_latest:+.0f}K',
        html,
        flags=re.DOTALL
    )

    # Core CPI sub
    html = re.sub(
        r'(CPI YoY.*?kpi-sub[^>]*>)Core [\d.]+%',
        f'\\g<1>Core {core_cpi:.1f}%',
        html,
        flags=re.DOTALL
    )

    # Core PCE sub
    html = re.sub(
        r'(PCE.*?kpi-sub[^>]*>)Core [\d.]+%',
        f'\\g<1>Core {pce_core:.1f}%',
        html,
        flags=re.DOTALL
    )

    # ═══ O. UPDATE LABOR TABLE ═══
    labor_updates = {
        "Unemployment": f"{ur:.1f}%",
        "NFP MoM": f"{nfp_latest:+.0f}K",
        "Avg Hourly Earnings": f"${fred['CES0500000003'][1]:.2f}",
        "JOLTS Openings": f"{fred['JTSJOL'][1]:,.0f}K",
        "JOLTS Hires": f"{fred['JTSHIL'][1]:,.0f}K",
        "JOLTS Layoffs": f"{fred['JTSLDL'][1]:,.0f}K",
        "Init. Claims": f"{claims_k:.0f}K",
        "UMich Sentiment": f"{sent:.1f}",
        "Debt Service %": f"{fred['TDSP'][1]:.1f}%",
        "CC Delinquency": f"{fred['DRCCLACBS'][1]:.1f}%",
    }
    for label, val in labor_updates.items():
        # Match: label</td><td>VALUE or label</td><td class="neg">VALUE or class="pos"
        html = re.sub(
            f'({re.escape(label)}</td><td[^>]*>)[^<]+',
            f'\\g<1>{val}',
            html,
            count=1
        )
    # Apply neg/pos class for NFP
    if nfp_latest < 0:
        html = re.sub(r'(NFP MoM</td><td)[^>]*(>)', f'\\g<1> class="neg"\\g<2>', html, count=1)
    else:
        html = re.sub(r'(NFP MoM</td><td)[^>]*(>)', f'\\g<1>\\g<2>', html, count=1)

    # ═══ WRITE UPDATED FILE ═══
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Dashboard updated successfully! ({today})")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("GTM Dashboard — Automated FRED Refresh")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Check HTML file exists
    if not os.path.exists(HTML_FILE):
        print(f"ERROR: {HTML_FILE} not found in current directory.")
        sys.exit(1)

    # Pull all data
    fred = pull_fred_data()
    nl = pull_nl_data()
    sofr = pull_sofr_spread()
    cpi_hist = pull_cpi_history()
    nfp_hist = pull_nfp_history()

    if nl is None:
        print("ERROR: NL calculation failed. Aborting.")
        sys.exit(1)

    nlspx = calc_nlspx_ratio(nl["history"])

    # Update HTML
    update_html(fred, nl, sofr, nlspx, cpi_hist, nfp_hist)

    # Summary
    print("\n" + "=" * 60)
    print("REFRESH SUMMARY")
    print("=" * 60)
    print(f"  S&P 500:      {fred['SP500'][1]:,.0f}")
    print(f"  10Y UST:      {fred['DGS10'][1]:.2f}%")
    print(f"  VIX:          {fred['VIXCLS'][1]:.1f}")
    print(f"  Net Liquidity: ${nl['nl_t']:.3f}T")
    print(f"  SOFR-IORB:    {(fred['SOFR'][1]-fred['IORB'][1])*100:+.0f} bps")
    print(f"  NL/SPX Ratio: {nlspx['current']:.2f} (mean {nlspx['mean']:.2f}, -1σ {nlspx['warn']:.2f})")
    print(f"  CPI:          {fred['CPIAUCSL'][1]:.2f}%")
    print(f"  NFP:          {nfp_hist[-1]['value']:+.0f}K")


if __name__ == "__main__":
    main()

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
HTML_FILE = "gtm-dashboard.html"

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

    # Latest values
    walcl = fetch_fred("WALCL", limit=1)
    tga = fetch_fred("WTREGEN", limit=1)
    rrp = fetch_fred("RRPONTSYD", limit=1)

    if not walcl or not tga or not rrp:
        print("ERROR: Could not fetch NL components")
        return None

    w_val = walcl[0][1]  # Millions
    t_val = tga[0][1]    # Millions
    r_val = rrp[0][1]    # Billions! Convert to Millions
    r_val_m = r_val * 1000

    nl_m = w_val - t_val - r_val_m
    nl_t = nl_m / 1_000_000

    print(f"  WALCL:  {w_val:,.0f}M  (${w_val/1e6:.3f}T)")
    print(f"  TGA:    {t_val:,.0f}M  (${t_val/1e6:.3f}T)")
    print(f"  RRP:    {r_val:,.1f}B → {r_val_m:,.0f}M")
    print(f"  NL:     {nl_m:,.0f}M  (${nl_t:.3f}T)")
    print(f"  Date:   {walcl[0][0]}")

    # History for chart (monthly sampling, weekly for last year)
    print("\n--- Building NL history for chart ---")
    walcl_hist = fetch_fred("WALCL", limit=600, start="2015-01-01", sort="asc")
    tga_hist = fetch_fred("WTREGEN", limit=600, start="2015-01-01", sort="asc")
    rrp_hist = fetch_fred("RRPONTSYD", limit=2000, start="2015-01-01", sort="asc")
    sp_hist = fetch_fred("SP500", limit=3000, start="2015-01-01", sort="asc")

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

    # Sample: monthly for old data, weekly for last 12 months
    cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    sampled = []
    seen_months = set()
    for item in nl_history:
        if item["date"] >= cutoff:
            sampled.append(item)  # Keep all weekly
        else:
            month_key = item["date"][:7]
            if month_key not in seen_months:
                seen_months.add(month_key)
                sampled.append(item)

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

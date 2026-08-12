#!/usr/bin/env python3
"""
refresh.py — IATI Bangladesh Donor Atlas data pipeline.

Takes a raw IATI Datastore CSV export for Bangladesh and produces:
  1. data/latest.json   — processed, theme-tagged, slim data (for the dashboard)
  2. index.html          — the standalone dashboard, ready for GitHub Pages

Usage:
    python refresh.py path/to/iati_export.csv

To pull a fresh CSV instead of using a local file, see fetch_from_iati()
below — stubbed out with the query you'd need; uncomment and adapt once
you've got the Datastore API working the way you want it.

No external dependencies beyond the Python standard library.
"""

import csv
import json
import sys
import os
import re
from collections import defaultdict, Counter
from datetime import datetime
from urllib.parse import quote

csv.field_size_limit(sys.maxsize)

# =====================================================================
# CONFIG — edit these as your needs evolve
# =====================================================================

FX_TO_USD = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067,
    "BDT": 0.0091, "SEK": 0.094, "NOK": 0.094, "DKK": 0.144,
    "CHF": 1.13, "AUD": 0.66, "CAD": 0.74, "CNY": 0.14,
    "KRW": 0.00075, "INR": 0.012, "AED": 0.272,
}

ORG_TYPE = {
    "10": "Government", "11": "Local Government", "15": "Other Public Sector",
    "21": "International NGO", "22": "National NGO", "23": "Regional NGO",
    "24": "Partner Country NGO", "30": "Public-Private Partnership",
    "40": "Multilateral", "60": "Foundation", "70": "Private Sector",
    "71": "Private Sector in Provider Country", "72": "Private Sector in Aid Recipient Country",
    "73": "Private Sector in Third Country", "80": "Academic / Research", "90": "Other",
}

POLICY_MARKER_LABELS = {
    "1": "Gender Equality", "2": "Aid to Environment",
    "3": "Participatory Dev / Good Governance", "4": "Trade Development",
    "5": "Biological Diversity", "6": "Climate Change Mitigation",
    "7": "Combat Desertification", "8": "Climate Change Adaptation",
    "9": "RMNCH", "10": "Disaster Risk Reduction", "11": "Disability", "12": "Nutrition",
}
SIGNIFICANCE_LABELS = {
    "0": "Not targeted", "1": "Significant", "2": "Principal",
    "3": "Principal & in support", "4": "Explicit primary obj.",
}
DOC_CATEGORY_LABELS = {
    "A01": "Impact appraisal", "A02": "Objectives / Purpose", "A03": "Intended beneficiaries",
    "A05": "Budget", "A07": "Evaluation", "A08": "Results / Outcomes", "A11": "Contract",
    "B01": "Annual report", "B06": "Audit report", "B09": "Institutional evaluation",
    "B10": "Country evaluation", "B11": "Sector strategy", "B12": "Thematic strategy",
    "B16": "Organisation website", "B17": "Annual aid publication",
}
DOC_PRIORITY = {
    "A07": 0, "A08": 1, "B09": 2, "B10": 3, "A02": 4, "A01": 5, "B11": 6, "B12": 7,
    "A03": 8, "A05": 9, "B17": 10, "B01": 11, "B06": 12, "B16": 13,
}

NAME_FIXES_KEY = {
    "Ministry of Foreign Affairs": "Ministry of Foreign Affairs (Netherlands)",
    "UK - Foreign": "UK FCDO",
    "Department for Environment": "UK DEFRA",
    "The Global Fund to Fight AIDS": "The Global Fund",
    "DEPARTMENT FOR BUSINESS": "UK Dept for Business, Energy & Industrial Strategy",
    "DEPARTMENT FOR SCIENCE": "UK Dept for Science, Innovation & Tech",
}

# Themes for Sida Bangladesh positioning — edit/add freely, this is the
# single place to change what the Topics tab covers.
THEMES = {
    "climate": {"label": "Climate Resilience & Adaptation",
        "keywords": ["climate","adapt","resilience","disaster","embankment","cyclone","flood",
                     "early warning","drought","ecosystem","DRR","vulnerab","low-carbon",
                     "mitigation","carbon","emission","green","GCF"],
        "sectors": ["Environment"], "policy_markers": ["8","6","10"]},
    "wee_gender": {"label": "Women, Gender & SRHR",
        "keywords": ["women","girls","gender","female","SRHR","reproductive","child marriage",
                     "GBV","violence against women","feminist","maternal","WEE"],
        "policy_markers": ["1","9"]},
    "governance": {"label": "Governance, Civil Society & Anti-Corruption",
        "keywords": ["governance","civil society","corruption","transparency","accountability",
                     "election","democracy","human rights","rule of law","media","press freedom",
                     "justice","village court","BALLOT","integrity","anti-trafficking"],
        "sectors": ["Government & Civil Society"], "policy_markers": ["3"]},
    "rohingya": {"label": "Rohingya Response & Cox's Bazar",
        "keywords": ["rohingya","refugee","cox's bazar","displacement","host community",
                     "myanmar","stateless","FDMN"], "humanitarian_flag_boost": True},
    "humanitarian": {"label": "Humanitarian Response (broader)",
        "keywords": ["humanitarian","emergency","crisis","disaster relief","appeal","cash for work"],
        "humanitarian_flag_boost": True, "sectors": ["Humanitarian"]},
    "drm_pfm": {"label": "DRM, PFM & Public Finance",
        "keywords": ["revenue","tax","VAT","public finance","expenditure","fiscal","procurement",
                     "audit","PFM","domestic resource","customs","NBR","treasury"]},
    "rmg_trade": {"label": "RMG, Industry & Trade",
        "keywords": ["garment","RMG","textile","ready-made","industry","trade","export",
                     "value chain","manufacturing","working conditions","labour","ILO",
                     "knit","apparel","leather","BGMEA"],
        "sectors": ["Industry & Trade","Trade Policy"], "policy_markers": ["4"]},
    "blended_msme": {"label": "Blended Finance, MSMEs & Private Sector",
        "keywords": ["MSME","SME","small and medium","private sector","blended","guarantee",
                     "equity","loan","credit","microfinance","MFI","financial inclusion",
                     "investment","bond","DGGF","DFI","PPP"],
        "sectors": ["Banking & Finance","Business & Other Services"]},
    "social_protection": {"label": "Social Protection & Safety Nets",
        "keywords": ["safety net","social protection","cash transfer","poverty reduction",
                     "income support","livelihood","Nuton Jibon"]},
    "energy": {"label": "Energy & Just Transition",
        "keywords": ["energy","power","electricity","renewable","solar","grid","coal",
                     "LNG","gas","transmission","RERED","off-grid"], "sectors": ["Energy"]},
    "health": {"label": "Health, Nutrition & Population",
        "keywords": ["health","nutrition","vaccine","TB","tuberculosis","malaria","HIV",
                     "AIDS","maternal","child health","antibiotic","stunting","WASH",
                     "tobacco","ultrasound","typhoid","HPV"],
        "sectors": ["Health & Population"], "policy_markers": ["12"]},
    "education": {"label": "Education & Skills",
        "keywords": ["education","school","learning","literacy","skills","training","TVET",
                     "vocational","teacher","student","out of school","university","higher education"],
        "sectors": ["Education"]},
    "wash": {"label": "WASH (Water, Sanitation, Hygiene)",
        "keywords": ["water","sanitation","hygiene","WASH","drinking water","wastewater",
                     "sewer","latrine"], "sectors": ["Water & Sanitation"]},
    "agriculture": {"label": "Agriculture, Food Security & Rural Dev.",
        "keywords": ["agriculture","rural","farmer","crop","fish","livestock","food security",
                     "smallholder","rice","irrigation","agri","horticulture","dairy"],
        "sectors": ["Agriculture & Rural Dev."]},
    "transport": {"label": "Transport, Connectivity & Infrastructure",
        "keywords": ["transport","road","rail","railway","port","airport","bridge","metro",
                     "MRT","logistics","connectivity"], "sectors": ["Transport & Storage"]},
    "climate_finance": {"label": "Climate Finance Specifically",
        "keywords": ["climate finance","GCF","Green Climate Fund","GEF","climate fund",
                     "carbon market","adaptation fund","loss and damage"]},
}

# Hand-written positioning angles — the one-sentence "why this matters for
# Sida" hook per theme. This is the bit pure automation can't write; edit
# these as your own analysis evolves. Pulled into the pre-baked summary.
POSITIONING_NOTES = {
    "climate": "Sweden's adaptation finance sits among many; the open question is whether Sida's locally-led adaptation angle (LoGIC-style) is differentiated enough from larger DFI-led climate infrastructure lending.",
    "wee_gender": "A genuinely crowded field with strong Nordic-aligned donors already present — the differentiation question is which sub-niche (SRHR, GBV, economic empowerment) is least saturated.",
    "governance": "High activity count is partly an SDC reporting-granularity artefact; on disbursed value the field is thinner than it looks, which may be where a strategic governance bet has more room to matter.",
    "rohingya": "Funding has visibly thinned since the 2022 peak; a coordination or financing-continuity angle may matter more here than new programming.",
    "humanitarian": "Overlaps heavily with the Rohingya theme; worth checking how much of this is protracted-crisis funding versus rapid-onset response capacity.",
    "drm_pfm": "Thin field, technical in nature, very long return horizon — a natural complement-not-compete space given few traditional donors prioritise it.",
    "rmg_trade": "ILO and a handful of bilateral donors anchor this; Sweden's Trade for Jobs angle would sit alongside rather than duplicate the dominant working-conditions agenda.",
    "blended_msme": "Active DFI-heavy space (IFC, Dutch FMO-adjacent vehicles); guarantee-plus-TA positioning likely fits better than another direct credit line, consistent with the existing liquidity-crowding read.",
    "social_protection": "World Bank-anchored via large safety-net lending; smaller donors are mostly downstream or complementary rather than co-funding at scale.",
    "energy": "JICA and EIB dominate by committed value through large infrastructure loans; a just-transition or off-grid niche is more open than grid-scale generation.",
    "health": "Crowded, well-resourced field led by Gates Foundation and Global Fund; differentiation likely needs to be thematic (e.g. NCDs, health financing) rather than volume-based.",
    "education": "Netherlands and World Bank-linked financing lead; girls' education and skills-to-employment bridges remain comparatively less contested.",
    "wash": "Dutch-led consortium work (Simavi, SDG WASH) is prominent; urban WASH and climate-resilient WASH appear less crowded than rural basic access.",
    "agriculture": "IFAD and World Bank anchor large lending; smallholder resilience and value-chain work leave room for smaller, more targeted positioning.",
    "transport": "Dominated by JICA, ADB and EIB mega-infrastructure loans — not a space where Sida's grant-based modality competes; better read as context for connectivity-dependent programming elsewhere.",
    "climate_finance": "Distinct from broader climate resilience — this is about access to GCF/GEF mechanisms themselves, where technical assistance on bankability may be a sharper niche than direct financing.",
}

# =====================================================================
# HELPERS
# =====================================================================

def sector_group(code):
    if not code or not code.isdigit(): return "Other / Unspecified"
    c = int(code)
    if 11100 <= c < 11500: return "Education"
    if 12100 <= c < 13100: return "Health & Population"
    if 13000 <= c < 14000: return "Health & Population"
    if 14000 <= c < 15000: return "Water & Sanitation"
    if 15000 <= c < 16000: return "Government & Civil Society"
    if 16000 <= c < 17000: return "Other Social Infrastructure"
    if 21000 <= c < 22000: return "Transport & Storage"
    if 22000 <= c < 23000: return "Communications"
    if 23000 <= c < 24000: return "Energy"
    if 24000 <= c < 25000: return "Banking & Finance"
    if 25000 <= c < 26000: return "Business & Other Services"
    if 31000 <= c < 32000: return "Agriculture & Rural Dev."
    if 32000 <= c < 33000: return "Industry & Trade"
    if 33000 <= c < 34000: return "Trade Policy"
    if 41000 <= c < 42000: return "Environment"
    if 43000 <= c < 44000: return "Multisector / Cross-cutting"
    if 51000 <= c < 53000: return "Budget Support / Debt"
    if 70000 <= c < 80000: return "Humanitarian"
    if 91000 <= c < 100000: return "Admin Costs / Other"
    return "Other / Unspecified"

def to_usd(val, cur):
    try: v = float(val)
    except (ValueError, TypeError): return 0.0
    rate = FX_TO_USD.get((cur or "").upper().strip(), None)
    return v * rate if rate else 0.0

def clean_name(name):
    if not name: return ""
    n = name.split(",")[0].strip().rstrip("\\").strip()
    for k, v in NAME_FIXES_KEY.items():
        if n.startswith(k): return v
    return n[:80]

def parse_csv_list(s):
    return s.split(",") if s else []

def source_link(iati_id):
    """d-portal.org is the standard public viewer for any IATI activity ID."""
    return f"https://d-portal.org/ctrack.html#view/act?aid={quote(iati_id)}"

def match_themes(title, desc, sectors_set, policy_markers_set, humanitarian):
    text = ((title or "") + " " + (desc or "")).lower()
    matched = []
    for tid, t in THEMES.items():
        score = 0
        for kw in t.get("keywords", []):
            if kw.lower() in text: score += 2; break
        for sec in t.get("sectors", []):
            if sec in sectors_set: score += 1; break
        for pm in t.get("policy_markers", []):
            if pm in policy_markers_set: score += 1; break
        if humanitarian and t.get("humanitarian_flag_boost"): score += 1
        if score >= 2: matched.append(tid)
    return matched

def parse_number(s):
    if not s: return None
    s = s.strip()
    if not s: return None
    try: return float(s)
    except ValueError: return None

# =====================================================================
# MAIN PROCESSING
# =====================================================================

def process_csv(path):
    org_data = defaultdict(lambda: {
        "name": "", "type": "", "activities": 0,
        "commitment_usd": 0.0, "disbursement_usd": 0.0,
        "sectors": Counter(), "themes": Counter(), "humanitarian": 0,
    })
    sector_totals = defaultdict(lambda: {"commitment": 0.0, "disbursement": 0.0, "activities": 0})
    yearly = defaultdict(lambda: {"commitment": 0.0, "disbursement": 0.0})
    theme_totals = defaultdict(lambda: {
        "commitment": 0.0, "disbursement": 0.0, "activities": 0,
        "orgs": Counter(), "org_types": Counter(), "with_results": 0,
    })
    org_type_counts = Counter()
    humanitarian_count = 0
    total_rows = 0
    unique_activities = set()
    activities_raw = []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            iati_id = (row.get("iati_identifier", "") or "").strip()
            unique_activities.add(iati_id)
            org_ref = row.get("reporting_org_ref", "") or "UNKNOWN"
            org_name = clean_name(row.get("reporting_org_narrative", ""))
            org_type = ORG_TYPE.get(row.get("reporting_org_type", ""), "Other / Unknown")
            title = (row.get("title_narrative", "") or "").strip()
            desc = (row.get("description_narrative", "") or "").split(",")[0].strip()
            humanitarian_flag = (row.get("humanitarian", "") or "").lower() in ("true", "1")

            org_type_counts[org_type] += 1
            if humanitarian_flag: humanitarian_count += 1

            sec_codes = parse_csv_list(row.get("sector_code"))
            sec_groups_here = {sector_group(sc.strip()) for sc in sec_codes if sc.strip()} or {"Other / Unspecified"}
            for g in sec_groups_here: sector_totals[g]["activities"] += 1

            # Policy markers
            pm_vocabs = parse_csv_list(row.get("policy_marker_vocabulary"))
            pm_codes = parse_csv_list(row.get("policy_marker_code"))
            pm_sigs = parse_csv_list(row.get("policy_marker_significance"))
            policy_markers, pm_codes_set, seen_pm = [], set(), set()
            for i in range(min(len(pm_codes), len(pm_sigs))):
                voc = pm_vocabs[i].strip() if i < len(pm_vocabs) else "1"
                if voc and voc != "1": continue
                code, sig = pm_codes[i].strip(), pm_sigs[i].strip()
                if not code or sig in ("0", ""): continue
                key = (code, sig)
                if key in seen_pm: continue
                seen_pm.add(key)
                policy_markers.append({"l": POLICY_MARKER_LABELS.get(code, f"Code {code}"),
                                        "s": SIGNIFICANCE_LABELS.get(sig, sig), "c": code})
                pm_codes_set.add(code)

            # Dates
            date_types = parse_csv_list(row.get("activity_date_type"))
            date_isos = parse_csv_list(row.get("activity_date_iso_date"))
            actual_start = planned_start = actual_end = planned_end = ""
            for i in range(min(len(date_types), len(date_isos))):
                t, d = date_types[i].strip(), date_isos[i].strip()[:10]
                if t == "1": planned_start = d
                elif t == "2": actual_start = d
                elif t == "3": planned_end = d
                elif t == "4": actual_end = d
            start_date = actual_start or planned_start
            end_date = actual_end or planned_end

            # Documents
            doc_urls = parse_csv_list(row.get("document_link_url"))
            doc_titles = parse_csv_list(row.get("document_link_title_narrative"))
            doc_cats = parse_csv_list(row.get("document_link_category_code"))
            docs, seen_urls = [], set()
            for i in range(min(len(doc_urls), 30)):
                url = doc_urls[i].strip()
                if not url or not url.startswith("http") or url in seen_urls: continue
                seen_urls.add(url)
                cat = doc_cats[i].strip() if i < len(doc_cats) else ""
                docs.append({"u": url, "t": (doc_titles[i].strip() if i < len(doc_titles) else "")[:120],
                             "c": DOC_CATEGORY_LABELS.get(cat, ""), "p": DOC_PRIORITY.get(cat, 99)})
            docs_sorted = sorted(docs, key=lambda x: x["p"])[:4]
            for d in docs_sorted: d.pop("p", None)

            # Results indicators
            r_titles = parse_csv_list(row.get("result_indicator_title_narrative"))
            r_measures = parse_csv_list(row.get("result_indicator_measure"))
            r_baselines = parse_csv_list(row.get("result_indicator_baseline_value"))
            r_baseline_years = parse_csv_list(row.get("result_indicator_baseline_year"))
            r_targets = parse_csv_list(row.get("result_indicator_period_target_value"))
            r_actuals = parse_csv_list(row.get("result_indicator_period_actual_value"))
            r_end_dates = parse_csv_list(row.get("result_indicator_period_period_end_iso_date"))
            results = []
            n_r = len(r_titles)
            for i in range(min(n_r, 8)):  # cap per activity
                rt = r_titles[i].strip() if i < len(r_titles) else ""
                if not rt: continue
                baseline = parse_number(r_baselines[i]) if i < len(r_baselines) else None
                target = parse_number(r_targets[i]) if i < len(r_targets) else None
                actual = parse_number(r_actuals[i]) if i < len(r_actuals) else None
                if baseline is None and target is None and actual is None: continue
                results.append({
                    "t": rt[:100],
                    "b": baseline, "tg": target, "ac": actual,
                    "by": r_baseline_years[i].strip() if i < len(r_baseline_years) else "",
                    "ed": (r_end_dates[i].strip()[:10] if i < len(r_end_dates) else ""),
                })
            has_results = len(results) > 0

            # Transactions
            tx_types = parse_csv_list(row.get("transaction_transaction_type_code"))
            tx_dates = parse_csv_list(row.get("transaction_transaction_date_iso_date"))
            tx_vals = parse_csv_list(row.get("transaction_value"))
            tx_curs = parse_csv_list(row.get("transaction_value_currency"))
            org_commit = org_disb = 0.0
            n = min(len(tx_types), len(tx_vals), len(tx_curs), len(tx_dates))
            for i in range(n):
                t = tx_types[i].strip()
                if t not in ("2", "3", "4"): continue
                v_usd = to_usd(tx_vals[i].strip(), tx_curs[i].strip())
                d4 = tx_dates[i].strip()[:4]
                if d4.isdigit():
                    yr = int(d4)
                    if 2010 <= yr <= 2030:
                        if t == "2": yearly[yr]["commitment"] += v_usd
                        elif t == "3": yearly[yr]["disbursement"] += v_usd
                if t == "2":
                    org_commit += v_usd
                    for g in sec_groups_here: sector_totals[g]["commitment"] += v_usd / len(sec_groups_here)
                elif t == "3":
                    org_disb += v_usd
                    for g in sec_groups_here: sector_totals[g]["disbursement"] += v_usd / len(sec_groups_here)

            themes_matched = match_themes(title, desc, sec_groups_here, pm_codes_set, humanitarian_flag)

            org_data[org_ref]["name"] = org_name or org_ref
            org_data[org_ref]["type"] = org_type
            org_data[org_ref]["activities"] += 1
            org_data[org_ref]["commitment_usd"] += org_commit
            org_data[org_ref]["disbursement_usd"] += org_disb
            for g in sec_groups_here: org_data[org_ref]["sectors"][g] += 1
            for tid in themes_matched: org_data[org_ref]["themes"][tid] += 1
            if humanitarian_flag: org_data[org_ref]["humanitarian"] += 1

            for tid in themes_matched:
                theme_totals[tid]["activities"] += 1
                theme_totals[tid]["commitment"] += org_commit / len(themes_matched)
                theme_totals[tid]["disbursement"] += org_disb / len(themes_matched)
                theme_totals[tid]["orgs"][org_name] += 1
                theme_totals[tid]["org_types"][org_type] += 1
                if has_results: theme_totals[tid]["with_results"] += 1

            activities_raw.append({
                "id": iati_id, "title": title, "desc": desc, "org": org_name, "org_type": org_type,
                "humanitarian": humanitarian_flag, "sectors": list(sec_groups_here), "themes": themes_matched,
                "policy_markers": policy_markers, "start": start_date, "end": end_date,
                "docs": docs_sorted, "results": results,
                "commitment_usd": org_commit, "disbursement_usd": org_disb,
            })

    return {
        "org_data": org_data, "sector_totals": sector_totals, "yearly": yearly,
        "theme_totals": theme_totals, "org_type_counts": org_type_counts,
        "humanitarian_count": humanitarian_count, "total_rows": total_rows,
        "unique_activities": unique_activities, "activities_raw": activities_raw,
    }

def generate_theme_summary(tid, theme_label, theme_stats, top_donors):
    """Pre-baked positioning summary — deterministic, built from computed
    stats plus the hand-written angle in POSITIONING_NOTES. No API call."""
    n_acts = theme_stats["activities"]
    disb = theme_stats["disbursement"]
    n_orgs = len(theme_stats["orgs"])
    results_pct = (theme_stats["with_results"] / n_acts * 100) if n_acts else 0
    top3 = [o for o, _ in theme_stats["orgs"].most_common(3)]
    top3_str = ", ".join(top3) if top3 else "no dominant reporter"

    lines = []
    lines.append(
        f"{n_orgs} organisations report {n_acts} activities in this theme, "
        f"totalling {disb/1e6:,.1f}M USD-equivalent disbursed. "
        f"The leading reporters are {top3_str}."
    )
    if results_pct > 0:
        lines.append(f"Roughly {results_pct:.0f}% of activities in this theme publish any result indicator data — treat that as a floor, not a verdict on performance.")
    else:
        lines.append("No activities in this theme publish result indicator data in this dataset.")
    angle = POSITIONING_NOTES.get(tid)
    if angle:
        lines.append(angle)
    return " ".join(lines)

def build_output(processed):
    org_data = processed["org_data"]
    sector_totals = processed["sector_totals"]
    yearly = processed["yearly"]
    theme_totals = processed["theme_totals"]
    activities_raw = processed["activities_raw"]

    org_list = []
    for ref, d in org_data.items():
        has_financials = (d["commitment_usd"] > 0 or d["disbursement_usd"] > 0)
        org_list.append({
            "ref": ref, "name": d["name"], "type": d["type"], "activities": d["activities"],
            "commitment_usd": round(d["commitment_usd"], 0), "disbursement_usd": round(d["disbursement_usd"], 0),
            "humanitarian": d["humanitarian"], "top_sectors": [s for s, _ in d["sectors"].most_common(3)],
            "themes": dict(d["themes"]), "has_financials": has_financials,
        })
    # Sort by union of disbursement and activity count so zero-financial
    # publishers (Sweden, Germany, Finland MFA, EU DG INTPA, Norad, etc.) don't
    # sink to the bottom of the org list — they're often among the largest
    # bilateral programmes even without transaction data in this export.
    org_list.sort(key=lambda x: (x["disbursement_usd"], x["activities"]), reverse=True)

    sec_list = [{"sector": s, "activities": d["activities"], "commitment_usd": round(d["commitment"], 0),
                 "disbursement_usd": round(d["disbursement"], 0)} for s, d in sector_totals.items()]
    sec_list.sort(key=lambda x: x["disbursement_usd"], reverse=True)

    themes_list = []
    for tid, d in theme_totals.items():
        themes_list.append({
            "id": tid, "label": THEMES[tid]["label"], "activities": d["activities"],
            "commitment_usd": round(d["commitment"], 0), "disbursement_usd": round(d["disbursement"], 0),
            "top_orgs": [{"name": n, "count": c} for n, c in d["orgs"].most_common(5)],
            "org_type_split": dict(d["org_types"]),
            "with_results": d["with_results"],
            "summary": generate_theme_summary(tid, THEMES[tid]["label"], d, d["orgs"]),
        })
    themes_list.sort(key=lambda x: x["disbursement_usd"], reverse=True)

    year_list = [{"year": y, "commitment_usd": round(yearly[y]["commitment"], 0),
                  "disbursement_usd": round(yearly[y]["disbursement"], 0)} for y in sorted(yearly.keys())]

    # ALL activities included — no material-value cap. The dashboard adds
    # pagination and org/theme/sector filters on the display side to keep the
    # ~3600-row browser experience responsive.
    activities_raw.sort(key=lambda x: max(x["commitment_usd"], x["disbursement_usd"]), reverse=True)
    top_acts = activities_raw

    acts_slim = []
    for a in top_acts:
        has_fin = (a["commitment_usd"] > 0 or a["disbursement_usd"] > 0)
        acts_slim.append({
            "i": a["id"][:60], "t": a["title"][:140],
            "ds": (a["desc"] or "")[:220],
            "o": a["org"][:60], "ot": a["org_type"], "h": 1 if a["humanitarian"] else 0,
            "s": a["sectors"], "th": a["themes"], "pm": a["policy_markers"][:5],
            "sd": a["start"], "ed": a["end"], "dc": a["docs"][:3],
            "rs": a["results"][:5],
            "c": int(a["commitment_usd"]), "d": int(a["disbursement_usd"]),
            "url": source_link(a["id"]), "hf": has_fin,
        })

    summary = {
        "total_rows": processed["total_rows"], "unique_activities": len(processed["unique_activities"]),
        "unique_orgs": len(org_data), "humanitarian_rows": processed["humanitarian_count"],
        "total_disbursement_usd": int(sum(o["disbursement_usd"] for o in org_list)),
        "total_commitment_usd": int(sum(o["commitment_usd"] for o in org_list)),
        "org_type_counts": dict(processed["org_type_counts"]),
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "orgs_without_financials": sum(1 for o in org_list if not o["has_financials"]),
    }

    # ALL orgs included — no cap. Filter panel in the dashboard uses this to
    # populate the "filter by organisation" dropdown for the Activities tab.
    orgs_slim = [{"n": o["name"], "t": o["type"], "a": o["activities"], "c": int(o["commitment_usd"]),
                  "d": int(o["disbursement_usd"]), "ts": o["top_sectors"], "th": o["themes"],
                  "hf": o["has_financials"]}
                 for o in org_list]

    out = {
        "summary": summary, "orgs": orgs_slim,
        "sectors": [{"s": s["sector"], "a": s["activities"], "c": int(s["commitment_usd"]),
                     "d": int(s["disbursement_usd"])} for s in sec_list],
        "yearly": [{"y": y["year"], "c": int(y["commitment_usd"]), "d": int(y["disbursement_usd"])} for y in year_list],
        "themes": [{"id": t["id"], "label": t["label"], "a": t["activities"], "c": int(t["commitment_usd"]),
                    "d": int(t["disbursement_usd"]), "to": t["top_orgs"], "ots": t["org_type_split"],
                    "wr": t["with_results"], "sm": t["summary"]} for t in themes_list],
        "activities": acts_slim,
    }
    return out

def fetch_from_iati(country="BD", out_path="iati_bangladesh.csv"):
    """
    Stub for pulling a fresh CSV directly from the IATI Datastore, instead
    of exporting manually from the website. Uncomment and adapt once you've
    confirmed the exact query parameters you want (the Datastore's CSV
    export endpoint accepts Solr-style queries).

    Docs: https://developer.iatistandard.org/

        import urllib.request
        url = (
            "https://api.iatistandard.org/datastore/activity/select"
            f"?q=recipient_country_code:{country}"
            "&rows=10000&wt=csv&fl=*"
        )
        req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": "YOUR_KEY"})
        with urllib.request.urlopen(req) as resp, open(out_path, "wb") as f:
            f.write(resp.read())
        return out_path
    """
    raise NotImplementedError("Fill in your Datastore API key and query, then call this instead of passing a local CSV.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python refresh.py path/to/iati_export.csv")
        sys.exit(1)
    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        sys.exit(1)

    print(f"Processing {csv_path} ...")
    processed = process_csv(csv_path)
    out = build_output(processed)

    os.makedirs("data", exist_ok=True)
    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"Wrote data/latest.json ({os.path.getsize('data/latest.json')/1024:.1f} KB)")

    # Build the HTML by injecting data into the template
    template_path = os.path.join(os.path.dirname(__file__), "template.html")
    if not os.path.exists(template_path):
        print("WARNING: template.html not found next to refresh.py — skipping HTML build.")
        print("Run this script from the repo root, or copy template.html alongside it.")
        return

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    data_json = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    html = template.replace("/*__DATA__*/", data_json)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote index.html ({os.path.getsize('index.html')/1024:.1f} KB)")
    print("Done. Commit and push to update the live GitHub Pages site.")

if __name__ == "__main__":
    main()

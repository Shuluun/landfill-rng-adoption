"""Merge batch1 + batch2 external verification, join to the 30-facility sample,
compute contamination rates + Wilson 95% CIs by stratum, write full table + summary.

Batch2 rows (22 facilities) are transcribed here from the four parallel subagent
hand-backs (verified 2026-11-09). batch1 rows read from batch1_verification.csv.
"""
import csv
import json
import math
import os

BASE = r"<PROJECT_ROOT>"
RUN = os.path.join(BASE, "outputs/2026-11-09_rng_adoption_date_validation_sample/run_001")
SAMPLE = os.path.join(RUN, "adoption_date_validation_sample.csv")
BATCH1 = os.path.join(RUN, "batch1_verification.csv")

# batch1 ext_source_url backfill (from reports/adoption_date_verification_pilot_batch1_20261109.md)
BATCH1_URLS = {
    1: "https://montaukrenewables.com/operations/johnstown-regional-energy-shade/",
    3: "https://kingcounty.gov/en/dept/dnrp/waste-services/garbage-recycling-compost/solid-waste-facilities/cedar-hills",
    9: "https://www.businesswire.com/news/home/20240125215412/en/5587848/",
    14: "https://edlenergy.com/project/lorain/",
    17: "https://news.cctexas.com/news/landfill-gas-project-expands-to-j-c-elliott-landfill",
    19: "https://www.bioenergy-news.com/news/archaeas-kentucky-landfill-to-rng-project-operational/",
    20: "https://www.tdlr.texas.gov/TABS/Projects/TABS2019009123",
    29: "https://ir.montaukrenewables.com/static-files/7986f9e7-eb21-48d9-a336-9838888b45cf",
}

FIELDS = ["sample_rank", "Landfill ID", "GHGRP ID", "Landfill Name", "State", "Ti", "era",
          "type", "ext_first_gas_year", "ext_first_gas_date", "ext_source_type",
          "ext_source_url", "ext_verdict", "ext_contamination_type", "ext_notes"]

# ---- batch2 (22 facilities) ----
B2 = [
    dict(sample_rank=2, LandfillID=1411, GHGRPID=1003269, name="Meadow Branch Landfill", state="TN", ti=2011, era="early<=2014", type="new",
         fgy=2011, fgd="", src="operator press", url="https://www.southerncompanygas.com/news/sustainability/how-one-tennessee-landfill-turns-emissions-into-lower-carbon-energy.html",
         verdict="clean", contam="", notes="Southern Company Gas: operating since 2011, first of its kind in eastern TN. Matches Ti=2011. No prior electricity/direct use surfaced; new correct."),
    dict(sample_rank=4, LandfillID=1195, GHGRPID=1007722, name="American LF", state="OH", ti=2014, era="early<=2014", type="switch",
         fgy="", fgd="", src="news", url="https://www.wastetodaymagazine.com/news/waste-management-renewable-natural-gas-facility/",
         verdict="uncertain", contam="", notes="WM injected cleaned LFG into Dominion East Ohio since ~2003/04 (prior Direct@2004 confirms switch) but public sources treat Milam (IL) as WM's first pipeline-quality RNG (2014). No public evidence of a distinct 2014 RNG switch at American; replacement first-gas year not established."),
    dict(sample_rank=5, LandfillID=1839, GHGRPID=1007879, name="Turnkey Recycling and Environmental Enterprise (TREE)", state="NH", ti=2009, era="early<=2014", type="switch",
         fgy=2009, fgd="2009-09", src="other", url="https://www.scsengineers.com/scs-project-case-stu/landfill-gas-lfge-university-of-new-hampshire-rochester-new-hampshire/",
         verdict="clean", contam="", notes="SCS Engineers EcoLine case study: RNG plant at TREE, construction Sept 2007, commercial operation Sept 2009 feeding UNH. Matches Ti=2009. Prior electricity 1992/1998 + direct 1991 confirms switch."),
    dict(sample_rank=6, LandfillID=2052, GHGRPID=1006026, name="City of Fort Smith Landfill", state="AR", ti=2006, era="early<=2014", type="switch",
         fgy=2006, fgd="", src="news", url="https://www.swtimes.com/story/business/2014/06/22/fort-smith-landfill-provides-natural/26374149007/",
         verdict="clean", contam="", notes="Southwest Times Record: facility built 2006 by Morrow Renewables + Cambrian Energy, injecting high-Btu gas. Matches Ti=2006. Prior direct use since 1998 confirms switch."),
    dict(sample_rank=7, LandfillID=688, GHGRPID=1002341, name="Laurel Ridge Landfill Inc.", state="KY", ti=2024, era="late>=2019", type="never_operational",
         fgy=2024, fgd="2024-10-30", src="news", url="https://bioenergyinternational.com/vision-rng-waste-connections-and-delta-gas-launch-kentucky-rng-facility/",
         verdict="status_contam", contam="stale_status_actually_operational; switch_mislabel", notes="Vision RNG + Waste Connections + Delta Gas started commercial ops 2024-10-30 (Bioenergy Intl 2024-10-31). LMOP Planned is stale. Prior Electricity@2003 -> true type switch (not never_operational)."),
    dict(sample_rank=8, LandfillID=816, GHGRPID=1007672, name="Elk River SLF Inc.", state="MN", ti=2024, era="late>=2019", type="never_operational",
         fgy="", fgd="", src="operator press", url="http://www.mmpa.org/news/mmpa-planning-renewable-natural-gas-plant-at-wms-elk-river-landfill/",
         verdict="status_contam", contam="never_built_counted_as_adoption", notes="MMPA announced plan only Nov 2022; FERC denied MMPA interconnection complaint Nov 2023; MMPA 2025 IRP still treats RNG as future/optional. No first-gas evidence. Ti=2024 counts a never-built project as adoption."),
    dict(sample_rank=10, LandfillID=1819, GHGRPID=1007799, name="Williamson County LF", state="TX", ti=2024, era="late>=2019", type="never_operational",
         fgy="", fgd="", src="other", url="https://wilco.bonfirehub.com/opportunities/147350",
         verdict="status_contam", contam="not_built", notes="County RFP #24RFP67 (LFG recovery/utilization) still under evaluation as of 2024-12-13, unawarded. No operational RNG. Planned Ti=2024 is projected, not real."),
    dict(sample_rank=11, LandfillID=2001, GHGRPID=1005255, name="North Country Environmental Services LF", state="NH", ti=2024, era="late>=2019", type="never_operational",
         fgy=2024, fgd="", src="operator press", url="https://www.businesswire.com/news/home/20240724881303/en/Viridi-Energy-Signs-20-Year-Agreement-With-nergir-L.P.-to-Supply-Pipeline-Quality-RNG-at-Scale",
         verdict="status_contam", contam="stale_status; switch_mislabel", notes="Viridi Energy rebuilt and brought online; 20-yr Energir offtake announced 2024-07-24, delivery from 2025. LMOP Construction is stale. Prior Direct@2001 -> true type switch."),
    dict(sample_rank=12, LandfillID=2048, GHGRPID=1003639, name="Temple Recycling & Disposal Facility", state="TX", ti=2024, era="late>=2019", type="never_operational",
         fgy=2024, fgd="2024-12-10", src="news", url="https://www.kcentv.com/article/news/community/renewable-natural-gas-facility-opens-temple-texas/500-1f7d64f3-33fe-4d7e-9f47-b15b964e5558",
         verdict="status_contam", contam="stale_status", notes="City of Temple + WM ~$50M RNG; first gas 2024-12-10 (KCEN). LMOP Planned is stale. Date actually matches Ti=2024; type resolves to new (operational, no prior use)."),
    dict(sample_rank=13, LandfillID=2323, GHGRPID=1006358, name="Winnebago Landfill", state="IL", ti=2024, era="late>=2019", type="never_operational",
         fgy=2024, fgd="2024-06-12", src="news", url="https://bioenergyinternational.com/nicor-gas-celebrates-its-first-rng-interconnection/",
         verdict="status_contam", contam="stale_status; switch_mislabel", notes="Air Liquide / Waga Energy WAGABOX; Nicor first IL RNG interconnection live 2024-06-12. LMOP Construction is stale. Prior Electricity@2008 + Direct@1998 -> true type switch."),
    dict(sample_rank=15, LandfillID=10407, GHGRPID=1003333, name="Gordon County Redbone Ridges LF", state="GA", ti=2024, era="late>=2019", type="never_operational",
         fgy="", fgd="", src="state permit", url="https://epd.georgia.gov/document/document/pa0223-3/download",
         verdict="status_contam", contam="not_operational", notes="Fidem Energy ~$50M RNG (GA EPD air permit) targeted Jan 2025; no confirmed first gas. Planned Ti=2024 is projected. Local GHGRP first report 2023 (new gas collection)."),
    dict(sample_rank=16, LandfillID=12144, GHGRPID=1004059, name="Quad Cities Landfill Phase IV", state="IL", ti=2024, era="late>=2019", type="never_operational",
         fgy="", fgd="", src="operator press", url="https://www.pinecreekrng.com/projects/quad-cities",
         verdict="status_contam", contam="stale_status", notes="Pine Creek RNG operational (1,400 SCFM into Kinder Morgan). LMOP Construction is stale. No exact first-gas date published. Operator is Millennium Waste, not Waste Management."),
    dict(sample_rank=18, LandfillID=11240, GHGRPID=1005253, name="Juniper Ridge Landfill", state="ME", ti=2024, era="late>=2019", type="new",
         fgy=2024, fgd="", src="news", url="https://ourcommunitynow.com/P/renewable-natural-gas-grows-in-maine",
         verdict="clean", contam="", notes="Archaea (BP) began processing gas at Juniper Ridge in 2024. Previously flared only -> new correct. Matches Ti=2024."),
    dict(sample_rank=21, LandfillID=1467, GHGRPID=1002645, name="Arlington LF", state="TX", ti=2019, era="late>=2019", type="switch",
         fgy=2019, fgd="", src="other", url="https://americanbiogascouncil.org/arlington-renewable-gas-facility-wins-national-innovation-award/",
         verdict="clean", contam="", notes="American Biogas Council 2019 Innovation of the Year, began operating 2019. Prior direct-use to Fort Worth + ~9MW generator confirms switch. Matches Ti=2019."),
    dict(sample_rank=22, LandfillID=1808, GHGRPID=1003646, name="Coastal Plains RDF", state="TX", ti=2020, era="late>=2019", type="switch",
         fgy=2020, fgd="", src="SEC filing", url="https://www.sec.gov/Archives/edgar/data/1826600/000119312522077310/d260478d10k.htm",
         verdict="clean", contam="", notes="Montauk Renewables 10-K: Coastal Plains COD 2020, converted LFG-to-electricity to RNG. Prior electricity 2003/2018 confirms switch. Matches Ti=2020."),
    dict(sample_rank=23, LandfillID=1879, GHGRPID=1008034, name="Arbor Hills Landfill", state="MI", ti=2023, era="late>=2019", type="switch",
         fgy=2023, fgd="", src="operator press", url="https://investors.opalfuels.com/news-releases/news-release-details/gfl-environmental-and-opal-fuels-complete-construction-renewable",
         verdict="clean", contam="", notes="GFL + OPAL Fuels Emerald RNG completed construction 2023-06-12, commercial ops later 2023. Prior electricity 1996/2007 confirms switch. Matches Ti=2023."),
    dict(sample_rank=24, LandfillID=2282, GHGRPID=1003406, name="Eco-Vista Landfill", state="AR", ti=2023, era="late>=2019", type="switch",
         fgy=2023, fgd="", src="operator press", url="https://mediaroom.wm.com/wm-unveils-new-35-million-dollar-eco-vista-renewable-natural-gas-facility",
         verdict="clean", contam="", notes="WM opened $35M Eco Vista RNG 2023-07-17 into Energy Transfer pipeline. Prior 4MW LFGTE (2010) confirms switch. Matches Ti=2023."),
    dict(sample_rank=25, LandfillID=1472, GHGRPID=1006227, name="Pine Hill Landfill", state="TX", ti=2017, era="mid2015-2018", type="new",
         fgy=2017, fgd="", src="news", url="https://www.kltv.com/story/36406324/methane-from-pine-hill-landfill-will-now-be-converted-to-renewable-natural-gas/",
         verdict="clean", contam="", notes="Republic Services + Morrow Renewables unveiled RNG Sep 2017. No prior electricity/direct use -> new correct. Matches Ti=2017."),
    dict(sample_rank=26, LandfillID=1497, GHGRPID=1003281, name="Seabreeze Environmental Landfill", state="TX", ti=2018, era="mid2015-2018", type="new",
         fgy=2018, fgd="", src="operator press", url="https://www.dtevantage.com/wp-content/uploads/2017/05/0-DTE-Biomass-Acquires-Renewable-Natural-Gas-Facilities-05-25-17.pdf",
         verdict="clean", contam="", notes="DTE Biomass acquired as development project May 2017, online ~2018 (greenfield). No prior use -> new correct. Matches Ti=2018."),
    dict(sample_rank=27, LandfillID=1757, GHGRPID=1001935, name="Sarpy County SLF", state="NE", ti=2018, era="mid2015-2018", type="new",
         fgy=2018, fgd="2018-07-12", src="other", url="https://arkleg.state.ar.us/Home/FTPDocument?path=%2FAssembly%2FMeeting+Attachments%2F510%2F2993%2FPwrPt-C5b+Cammack-BiogasBlack+Hills+10-3-19.pdf",
         verdict="clean", contam="", notes="Black Hills Energy: in-service 2018-07-12. Previously flared only -> new correct. Matches Ti=2018 exactly."),
    dict(sample_rank=28, LandfillID=516, GHGRPID=1008269, name="Milam Recycling and Disposal Facility", state="IL", ti=2015, era="mid2015-2018", type="switch",
         fgy=2014, fgd="", src="news", url="https://waste-management-world.com/artikel/waste-management-opens-19m-landfill-gas-grid-injection-facility-in-illinois/",
         verdict="clean", contam="", notes="WM opened Nov 2014, injection early Dec 2014 (~3mo before LMOP 2015-03-01; within 12mo tolerance). Prior 2.4MW LFGTE confirms switch."),
    dict(sample_rank=30, LandfillID=2207, GHGRPID=1002359, name="City of Charleston Landfill", state="WV", ti=2018, era="mid2015-2018", type="switch",
         fgy=2018, fgd="", src="state permit", url="https://dep.wv.gov/daq/permitting/titlevpermits/Documents/August%202018/Charleston%20Sanitary%20Landfill%20MM01%208-21%20FFS.pdf",
         verdict="clean", contam="", notes="WV DEP Title V permit mod (Aug 2018) removed LFGTE engines, installed high-Btu RNG upgrade. Prior electricity 2011 confirms switch. Matches Ti=2018; exact first-gas day unconfirmed."),
]

# ---- load batch1 ----
b1 = {}
with open(BATCH1, newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        b1[int(r["sample_rank"])] = r

# ---- load sample metadata (Landfill ID / GHGRP ID / County) ----
sample_meta = {}
with open(SAMPLE, newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        sample_meta[int(r["sample_rank"])] = r

# ---- assemble 30 rows ----
rows = []
for rk in sorted(set(list(b1.keys()) + [d["sample_rank"] for d in B2])):
    if rk in b1:
        r = b1[rk]
        # normalize batch1 contamination sub-tags to match batch2 taxonomy
        ct = r["ext_contamination_type"]
        if rk == 9:
            ct = "never_built_counted_as_adoption"
        elif rk == 14:
            ct = "stale_status_actually_operational; switch_mislabel"
        rows.append({
            "sample_rank": rk,
            "Landfill ID": r["Landfill ID"],
            "GHGRP ID": r["GHGRP ID"],
            "Landfill Name": r["Landfill Name"],
            "State": r["State"],
            "Ti": r["Ti"],
            "era": r["era"],
            "type": r["type"],
            "ext_first_gas_year": r["ext_first_gas_year"],
            "ext_first_gas_date": r["ext_first_gas_date"],
            "ext_source_type": r["ext_source_type"],
            "ext_source_url": BATCH1_URLS.get(rk, ""),
            "ext_verdict": r["ext_verdict"],
            "ext_contamination_type": ct,
            "ext_notes": r["ext_notes"],
        })
    else:
        d = [x for x in B2 if x["sample_rank"] == rk][0]
        rows.append({
            "sample_rank": rk,
            "Landfill ID": d["LandfillID"],
            "GHGRP ID": d["GHGRPID"],
            "Landfill Name": d["name"],
            "State": d["state"],
            "Ti": d["ti"],
            "era": d["era"],
            "type": d["type"],
            "ext_first_gas_year": d["fgy"],
            "ext_first_gas_date": d["fgd"],
            "ext_source_type": d["src"],
            "ext_source_url": d["url"],
            "ext_verdict": d["verdict"],
            "ext_contamination_type": d["contam"],
            "ext_notes": d["notes"],
        })

rows.sort(key=lambda x: int(x["sample_rank"]))

# ---- write full table ----
full_csv = os.path.join(RUN, "full_verification_30.csv")
with open(full_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)

# ---- stats ----
def wilson(k, n, z=1.96):
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    margin = z * math.sqrt((p*(1-p) + z*z/(4*n))/n) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))

def verdict_is_contam(v):
    return v in ("status_contam", "switch_mislabel", "date_drift")

# overall (exclude uncertain)
rated = [r for r in rows if r["ext_verdict"] != "uncertain"]
k_all = sum(1 for r in rated if verdict_is_contam(r["ext_verdict"]))
n_all = len(rated)

# by type stratum (exclude uncertain)
def stratum_stats(key, val):
    rr = [r for r in rows if r[key] == val and r["ext_verdict"] != "uncertain"]
    k = sum(1 for r in rr if verdict_is_contam(r["ext_verdict"]))
    return (val, len(rr), k)

type_stats = [stratum_stats("type", t) for t in ("new", "switch", "never_operational")]

# never_operational sub-split (explicit rank sets; ground truth from verification)
NO_NOT_BUILT = {8, 9, 10, 15}   # Enid, Elk River, Williamson, Gordon
NO_STALE = {7, 11, 12, 13, 14, 16}  # Laurel Ridge, North Country, Temple, Winnebago, Lorain, Quad Cities
NO_SWITCH_MISLABEL = {7, 11, 13, 14}  # prior-use misclassified out of switch
no = [r for r in rows if r["type"] == "never_operational"]
nobuilt = [r for r in no if int(r["sample_rank"]) in NO_NOT_BUILT]
nostale = [r for r in no if int(r["sample_rank"]) in NO_STALE]
noswitch = [r for r in no if int(r["sample_rank"]) in NO_SWITCH_MISLABEL]

summary = {
    "n_total": len(rows),
    "n_uncertain": sum(1 for r in rows if r["ext_verdict"] == "uncertain"),
    "n_rated": n_all,
    "n_clean": sum(1 for r in rated if r["ext_verdict"] == "clean"),
    "n_contaminated": k_all,
    "contamination_rate": k_all / n_all if n_all else None,
    "wilson_95ci_overall": list(wilson(k_all, n_all)),
    "by_type": [
        {"type": t, "n_rated": n, "n_contaminated": k, "rate": (k/n if n else None), "wilson_95ci": list(wilson(k, n))}
        for (t, n, k) in type_stats
    ],
    "never_operational_split": {
        "n_total": len(no),
        "n_not_built_or_not_operational": len(nobuilt),
        "n_stale_status_actually_operational": len(nostale),
        "n_switch_mislabel": len(noswitch),
    },
    "never_operational_ranks_not_built": [r["sample_rank"] for r in nobuilt],
    "never_operational_ranks_stale": [r["sample_rank"] for r in nostale],
}

summary_json = os.path.join(RUN, "verification_summary.json")
with open(summary_json, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

# ---- print ----
print(f"TOTAL rows: {len(rows)} | uncertain(excl): {summary['n_uncertain']} | rated: {n_all}")
print(f"CLEAN: {summary['n_clean']}  CONTAMINATED: {k_all}  RATE: {k_all/n_all:.1%}  Wilson95: [{summary['wilson_95ci_overall'][0]:.1%}, {summary['wilson_95ci_overall'][1]:.1%}]")
print()
print("BY TYPE STRATUM (uncertain excluded):")
for t, n, k in type_stats:
    lo, hi = wilson(k, n)
    print(f"  {t:<18} n_rated={n:>2}  contaminated={k:>2}  rate={k/n if n else 0:>6.1%}  Wilson95=[{lo:.1%}, {hi:.1%}]")
print()
print("NEVER_OPERATIONAL SPLIT:")
print(f"  not_built/not_operational : {len(nobuilt)}  ranks {summary['never_operational_ranks_not_built']}")
print(f"  stale_status_operational  : {len(nostale)}  ranks {summary['never_operational_ranks_stale']}")
print(f"  switch_mislabel (secondary): {len(noswitch)}")
print()
print("WROTE", full_csv)
print("WROTE", summary_json)

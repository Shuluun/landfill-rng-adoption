"""Merge the 10 already-verified + 26 newly-verified never_operational facilities into
a full 36-facility verdict table and compute the MEASURED false-adoption rate (replacing
the previous interval estimate ~40% [16.8%, 68.7%]).

Classification (consistent with merge_analyze_verification_20261109.py):
  class = false_adoption   -> Ti=2024 counted but facility never reached operation as of
                              the 2026-11-09 audit (cancelled, or still Planned/Construction)
  class = real_late_adoption -> facility actually reached commercial operation (LMOP status stale)
  class = uncertain        -> no public evidence, or contradictory evidence
Excluded from numerator/denominator of the rate: uncertain.

The 26 results come from 5 parallel external-verification subagents + 6 spot-checks
(done 2026-11-09). Bayview (LF 1539) was DOWNGRADED to uncertain because the cited
source does not name Bayview and GHGRP shows zero rows.
"""
import argparse, csv, datetime as dt, json, math, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/2026-11-09_rng_never_operational_verify/run_002'

# ---- 10 already-verified (from the 30-sample); class assigned from the earlier rank sets ----
B1 = [
    # lid, class, contam, switch_mislabel
    (688,  'real_late_adoption', 'stale_status_actually_operational', True),   # Laurel Ridge
    (816,  'false_adoption',     'never_built_counted_as_adoption', False),    # Elk River
    (1223, 'false_adoption',     'never_built_counted_as_adoption', False),    # Enid City
    (1819, 'false_adoption',     'not_built',                       False),    # Williamson County
    (2001, 'real_late_adoption', 'stale_status_actually_operational', True),   # North Country
    (2048, 'real_late_adoption', 'stale_status_actually_operational', False),  # Temple
    (2323, 'real_late_adoption', 'stale_status_actually_operational', True),   # Winnebago
    (2429, 'real_late_adoption', 'stale_status_actually_operational', True),   # Lorain
    (10407,'false_adoption',     'not_operational',                  False),   # Gordon County
    (12144,'real_late_adoption', 'stale_status_actually_operational', False),  # Quad Cities
]

# ---- 26 newly verified. class from subagent evidence + spot-check corrections. ----
# fields: lid, ghgrp, name, state, class, first_gas_year, source_type, source_url, switch_mislabel, notes
B2 = [
    (9, 1006186, 'Coffee County Sanitary Landfill', 'AL', 'real_late_adoption', 2025,
     'government', 'https://coffeecounty.us/174/Landfill-Gas', False,
     'NextEra/Southeast Gas placed AL first RNG in service 2025; Ti=2024 was planned, actual 2025.'),
    (20, 1007875, 'Magnolia Subtitle D MSW LF', 'AL', 'real_late_adoption', 2025,
     'operator press', 'https://www.energytech.com/energy-efficiency/news/55286936/viridi-energy-puts-new-rng-facility-into-commercial-operations-at-alabama-landfill', False,
     'Viridi commercial operation Q1 2025 (announced 2025-04-30); Ti=2024 planned, slipped to 2025.'),
    (184, 1004011, 'Keller Canyon LF', 'CA', 'real_late_adoption', 2024,
     'news', 'https://pgjonline.com/16107', True,
     'Ameresco/Republic/PG&E began commercial ops July 2024 (spot-checked). Prior Electricity@2009 -> switch.'),
    (460, 1003959, 'Columbus-Schatulga Road SLF', 'GA', 'false_adoption', None,
     'news', 'https://gulfoilandgas.com/webpro1/main/mainnews.asp?id=1148333', False,
     'RNG plant is at adjacent Pine Grove LF, not Schatulga (shared Project ID 180904; spot-checked). Schatulga closed, no own RNG.'),
    (495, 1007992, 'Countryside LF', 'IL', 'false_adoption', None,
     'other', 'https://salasobrien.com/projects/landfill-renewable-natural-gas-facility/', True,
     'Built ~2022 (Mas Energy/Terreva) but no public confirmation of commercial operation; still Construction as of late 2026. Prior Electricity -> switch.'),
    (554, 1007520, 'National Serv-All LF', 'IN', 'real_late_adoption', 2024,
     'news', 'https://www.naturalgasworld.com/bps-archaea-energy-republic-services-launch-first-rng-plant-in-fort-wayne-117782', True,
     'bp/Archaea+Republic Lightning Renewables launched June 2024, online summer 2024. Prior Electricity/Direct -> switch.'),
    (559, 1007833, 'Prairie View RDF', 'IN', 'real_late_adoption', 2023,
     'operator press', 'https://www.kindermorgan.com/ETV/KM-RNG/Resources/Insights/Introducing-Prairie-View-RNG?ROIID=365.29022', True,
     'Kinder Morgan commercial in-service 2023-12-20 (earlier than Ti=2024). Prior Electricity -> switch.'),
    (679, 1005270, 'Rumpke/Montgomery County LF', 'KY', 'real_late_adoption', 2024,
     'news', 'https://www.bioenergy-news.com/news/bps-archaea-energy-opens-rng-plant-in-kentucky/', False,
     'bp/Archaea ribbon cutting 2024-04-17, first-of-kind KY. No prior use -> new.'),
    (705, 1006462, 'Mundy Landfill', 'LA', 'false_adoption', None,
     'news', 'https://desotoparishjournal.com/2024/01/12/message-from-the-desoto-parish-policy-jury-administrator/', False,
     'Vitol BioMethane project still pending/under construction; GHGRP zero rows 2010-2024 (never collected gas).'),
    (829, 1003514, 'Central Missouri SLF', 'MO', 'real_late_adoption', 2025,
     'news', 'https://www.sfccmo.edu/gfl-environmental-donates-15000-to-support-agriculture-and-technical-training-at-sfcc/', True,
     'GFL first RNG began production Aug 2025. Prior Electricity@2014 -> switch.'),
    (838, 1007023, 'Lemons East/West Landfill', 'MO', 'real_late_adoption', None,
     'news', 'https://www.kbsi23.com/news/a-new-natural-gas-plant-in-dexter-is-set-to-begin-operations-in-the-coming-weeks/', False,
     'bp/Archaea+Republic grand opening Nov 2024, operating by 2025; no explicit first-gas date. No prior use -> new.'),
    (945, 1007298, 'Middlesex County LF', 'NJ', 'false_adoption', None,
     'news', 'https://biogascommunity.com/2026/10/12/pathway-to-the-mcua-rng-project-building-the-next-generation-of-integrated-landfill-to-fuel-infrastructure/', True,
     'MCUA RNG under construction as of Oct 2026 (no first gas). Prior Electricity -> switch.'),
    (1080, 1003101, 'East Carolina Regional LF', 'NC', 'uncertain', None,
     'none', '', False,
     'Lightning Renewables/Archaea; NCUC interconnection approved 2023, no public first-gas evidence found.'),
    (1150, 1005274, 'Wayne County LF', 'NC', 'uncertain', None,
     'none', '', True,
     'Terreva RNG; NCUC RIA approved May 2024, target Dec 2024, no first-gas confirmation found. Prior Electricity@2010 -> switch.'),
    (1238, 1003232, 'Knott Landfill', 'OR', 'false_adoption', None,
     'operator press', 'https://www.cngc.com/cascade-natural-gas-announces-decision-on-knott-landfill-renewable-natural-gas-project/', False,
     'Cascade Natural Gas announced 2026-10-22 it will NOT proceed (cost + OCP rulemaking); never built (spot-checked).'),
    (1415, 1002650, 'Middle Point Landfill', 'TN', 'real_late_adoption', 2025,
     'state permit', 'https://dataviewers.tdec.tn.gov/dataviewers/f?p=19031:34031::::34031:P34031_SITE_ID:8785', True,
     'Republic/Archaea Lightning Renewables ~$70M; start-up notification 2025-12-18, operating 2025. Prior Electricity -> switch.'),
    (1539, 1006417, 'Bayview LF', 'UT', 'uncertain', None,
     'operator press', 'https://www.pinecreekrng.com/pr/constellation-and-pine-creek-rng-announce-equity-purchase-agreement-in-rng-facilities', False,
     'DOWNGRADED: source says Pine Creek has 5 facilities in WA/UT/IA/IL but does not name Bayview; GHGRP zero rows. Cannot confirm operational.'),
    (1624, 1007090, 'Horn Rapids Landfill', 'WA', 'real_late_adoption', 2024,
     'government', 'https://flashalert.net/id/CityofRichland/171085', False,
     'City of Richland grand opening 2024-04-02, injecting into Cascade system. Flared before -> new.'),
    (2068, 1006132, 'Autumn Hills RDF', 'MI', 'real_late_adoption', 2025,
     'operator press', 'https://www2.kindermorgan.com/ETV/KM-RNG/Leaders-in-RNG-Development/Renewable-Gas-Assets/Autumn-Hills-RNG', True,
     'Kinder Morgan first MI plant came online March 2025. Prior Direct/Electricity -> switch.'),
    (2165, 1003446, 'Ada County Landfill', 'ID', 'real_late_adoption', 2025,
     'operator press', 'https://biogasdev.com/projects/landfill-rng-boise-id/', True,
     'Biogas Development Hidden Hollow commercial operation since April 2025 (ID first RNG). Prior Electricity@2006 -> switch.'),
    (2336, 1004118, 'Sampson County Disposal LLC', 'NC', 'real_late_adoption', 2024,
     'operator press', 'https://www.prnewswire.com/news-releases/gfl-environmental-and-opal-fuels-begin-commercial-operations-of-their-second-rng-facility-302268705.html', True,
     'GFL+OPAL commercial operations 2024-10-07. Prior Electricity@2011/2014 -> switch.'),
    (2424, 1002236, 'Anson County WM Facility', 'NC', 'false_adoption', None,
     'other', 'https://landfillgroup.com/anson-county-landfill-project/', False,
     'Anson Gas Producers under construction; NCUC Nov 2022, Title V May 2024; no first-gas confirmation.'),
    (10520, 1003863, 'Columbus Pine Grove MSWLF', 'GA', 'real_late_adoption', 2026,
     'operator press', 'https://gulfoilandgas.com/webpro1/main/mainnews.asp?id=1148333', False,
     'The Landfill Group/LS Power Columbus Power Producers commercial op 2026-08-10 (spot-checked). Shared Project ID 180904 with LF 460.'),
    (10620, 1004408, 'South Wake LF (New)', 'NC', 'real_late_adoption', 2025,
     'government', 'https://wake.legistar.com/LegislationDetail.aspx?ID=8065811&GUID=2540B7C3-A5B2-4EE7-B133-E17B333CC709', True,
     'Wake Co + Archaea conversion; operational by mid-2026 (RINs); first gas ~Oct 2025. Prior Electricity@2013 -> switch.'),
    (11120, 1004010, 'Forward Landfill', 'CA', 'false_adoption', None,
     'other', 'https://forwardlandfill.com/what-we-do/', True,
     'Ameresco RNG under construction as of Nov 2026 (expected end 2026); no first gas. Prior Electricity@2014 -> switch.'),
    (21203, 1007615, 'Fairless Landfill', 'PA', 'real_late_adoption', 2025,
     'operator press', 'https://americanbiogascouncil.org/wm-opens-131-million-renewable-natural-gas-rng-facility-in-suburban-philadelphia/', False,
     'WM $131M RNG opened 2025-04-24 (spot-checked). No prior use -> new.'),
]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float('nan'), float('nan'), float('nan'))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, center - half, center + half)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)

    # load the 10-sample never_operational rows from full_verification_30.csv for name/state/ghgrp
    f30 = ROOT / 'outputs/2026-11-09_rng_adoption_date_validation_sample/run_001/full_verification_30.csv'
    b1_meta = {}
    with open(f30, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            lid = int(row['Landfill ID'])
            if lid in {x[0] for x in B1}:
                b1_meta[lid] = row

    rows = []
    for lid, cls, contam, sw in B1:
        m = b1_meta[lid]
        rows.append({
            'Landfill ID': lid, 'GHGRP ID': m['GHGRP ID'], 'Landfill Name': m['Landfill Name'],
            'State': m['State'], 'Ti': 2024, 'class': cls,
            'ext_first_gas_year': m['ext_first_gas_year'] or None,
            'ext_source_type': m['ext_source_type'], 'ext_source_url': m['ext_source_url'],
            'switch_mislabel': sw, 'contamination_type': contam, 'ext_notes': m['ext_notes'],
        })
    for lid, ghgrp, name, state, cls, fgy, stype, url, sw, notes in B2:
        rows.append({
            'Landfill ID': lid, 'GHGRP ID': ghgrp, 'Landfill Name': name, 'State': state,
            'Ti': 2024, 'class': cls, 'ext_first_gas_year': fgy,
            'ext_source_type': stype, 'ext_source_url': url,
            'switch_mislabel': sw, 'contamination_type': ('' if cls == 'uncertain' else ('stale_status_actually_operational' if cls == 'real_late_adoption' else 'never_built_counted_as_adoption' if fgy is None and cls == 'false_adoption' else 'not_operational')), 'ext_notes': notes,
        })

    rows.sort(key=lambda r: r['Landfill ID'])
    n_total = len(rows)
    n_uncertain = sum(1 for r in rows if r['class'] == 'uncertain')
    n_rated = n_total - n_uncertain
    n_false = sum(1 for r in rows if r['class'] == 'false_adoption')
    n_real = sum(1 for r in rows if r['class'] == 'real_late_adoption')
    n_switch_mislabel = sum(1 for r in rows if r['switch_mislabel'])

    p, lo, hi = wilson(n_false, n_rated)

    # write CSV
    fieldnames = ['Landfill ID', 'GHGRP ID', 'Landfill Name', 'State', 'Ti', 'class',
                  'ext_first_gas_year', 'ext_source_type', 'ext_source_url',
                  'switch_mislabel', 'contamination_type', 'ext_notes']
    with open(out / 'never_operational_full_36_final.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)

    summary = {
        'n_total': n_total, 'n_uncertain': n_uncertain, 'n_rated': n_rated,
        'n_false_adoption': n_false, 'n_real_late_adoption': n_real,
        'n_switch_mislabel': n_switch_mislabel,
        'false_adoption_rate': round(p, 4),
        'false_adoption_wilson95': [round(lo, 4), round(hi, 4)],
        'false_adoption_ids': sorted(r['Landfill ID'] for r in rows if r['class'] == 'false_adoption'),
        'real_late_adoption_ids': sorted(r['Landfill ID'] for r in rows if r['class'] == 'real_late_adoption'),
        'uncertain_ids': sorted(r['Landfill ID'] for r in rows if r['class'] == 'uncertain'),
        'switch_mislabel_ids': sorted(r['Landfill ID'] for r in rows if r['switch_mislabel']),
    }
    (out / 'never_operational_36_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nfalse adoption rate = {n_false}/{n_rated} = {p:.1%}  Wilson95 [{lo:.1%}, {hi:.1%}]")
    print(f"real late adoption = {n_real}, switch_mislabel = {n_switch_mislabel}, uncertain = {n_uncertain}")


if __name__ == '__main__':
    main()

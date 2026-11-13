"""Key-based original locators and scoped local EIA coverage for Mallard."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import json
import re
import sys
import zipfile
from collections import Counter
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rng.evidence import load, sha, locate_keyed_records


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self.ignored += 1
        if not self.ignored and tag in {'p', 'h1', 'h2', 'h3', 'time', 'li'}:
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'}:
            self.ignored = max(0, self.ignored-1)
        if not self.ignored and tag in {'p', 'h1', 'h2', 'h3', 'time', 'li'}:
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    args = parser.parse_args()
    out = (ROOT / args.run_dir).resolve()
    assert out.is_relative_to(ROOT / 'outputs')
    out.mkdir(parents=True, exist_ok=False)
    config = load(ROOT / 'config/rng_pilot.json')
    freeze = load(ROOT / config['inputs']['freeze'])
    psource = load(ROOT / config['inputs']['plant_source'])
    isource = load(ROOT / config['inputs']['inventory_source'])
    inventory = ROOT / isource['local_path']
    lmop = ROOT / freeze['input_path']
    plant = ROOT / psource['local_original']
    before = {str(p.relative_to(ROOT)): sha(p) for p in [inventory, lmop, plant]}
    fields = ['Plant ID','Plant Name','Generator ID','Energy Source Code','Operating Month','Operating Year',
              'Retirement Month','Retirement Year','Latitude','Longitude']
    gen1 = locate_keyed_records(inventory, 'Retired', {'Plant ID': 55013, 'Generator ID': 'GEN1'}, fields)
    retired = locate_keyed_records(inventory, 'Retired', {'Plant ID': 55013}, fields)
    operating = locate_keyed_records(inventory, 'Operating', {'Plant ID': 55013}, fields)
    old_plant = locate_keyed_records(plant, 'Plant', {'Plant Code': 55013}, ['Plant Code','Plant Name','Street Address','State','County'])
    reg = locate_keyed_records(lmop, 'LMOP Database', {'Landfill ID': 1676},
            ['Landfill ID','Landfill Name','Physical Address','City','State','County','Zip Code','Latitude','Longitude',
             'Project ID','Current Project Status','Project Type Category','Project Start Date','Project Shutdown Date'])
    assert gen1['matched_count'] == 1 and retired['matched_count'] == 3 and reg['matched_count'] == 2
    gen1['id_namespace'] = 'EIA Plant ID + within-plant Generator ID'
    reg['id_namespace'] = 'EPA LMOP Landfill ID;1676 is not an EIA Plant ID, ORIS or Wisconsin FID'
    write(out / 'ORIGINAL_LOCATORS.json', {'gen1': gen1, 'all_retired_units': retired, 'lmop_records': reg})
    raw_path = ROOT / config['inputs']['generation']
    raw = load(raw_path)
    records = raw['response']['data']
    exact = [r for r in records if str(r['plantCode']) == '55013']
    allfuel_path = raw_path.with_name('eia_three_cases_allfuels_2015_2024.json')
    allfuel = load(allfuel_path)['response']['data']
    coverage = {
        'scope': 'Registered local EIA inputs only; no claim about unacquired annual EIA923 originals or all files on disk',
        'filtered_generation_extract': {'path': str(raw_path.relative_to(ROOT)), 'sha256': sha(raw_path), 'format': 'API JSON, no worksheets',
            'records': len(records), 'years': sorted({r['period'] for r in records}),
            'filters': {'fuel2002': sorted({r['fuel2002'] for r in records}), 'primeMover': sorted({r['primeMover'] for r in records})},
            'raw_units': sorted({r['generation-units'] for r in records}), 'plant_id_formats': sorted({type(r['plantCode']).__name__ for r in records}),
            'target_records': len(exact), 'status': 'CURRENT_FILTERED_EXTRACT_NO_TARGET_ROWS_NOT_FULL_ANNUAL_SOURCE_ABSENCE'},
        'three_pilot_allfuel_extract': {'path': str(allfuel_path.relative_to(ROOT)), 'sha256': sha(allfuel_path), 'records': len(allfuel),
            'plant_ids': sorted({str(r['plantCode']) for r in allfuel}), 'target_in_covered_plant_ids': any(str(r['plantCode']) == '55013' for r in allfuel),
            'status': 'PILOT_SUBSET_DOES_NOT_ESTABLISH_MALLARD_ANNUAL_COVERAGE'},
        'plant2017_original': {'path': str(plant.relative_to(ROOT)), 'sheet': old_plant['sheet'],
            'scanned_records': old_plant['scanned_records_with_primary_key'], 'target_records': old_plant['matched_count'],
            'status': 'COMPLETE_LOCAL_2017_IDENTITY_SHEET_CHECKED_NOT_ANNUAL_GENERATION'},
        'inventory2026_original': {'path': str(inventory.relative_to(ROOT)),
            'retired_scanned': retired['scanned_records_with_primary_key'], 'retired_target': retired['matched_count'],
            'operating_scanned': operating['scanned_records_with_primary_key'], 'operating_target': operating['matched_count'],
            'status': 'COMPLETE_LOCAL_SNAPSHOT_MAIN_STATUS_SHEETS_CHECKED_NOT2015_2024_GENERATION'},
        'annual_full_eia923_originals': {'status': 'COVERAGE_NOT_CONFIRMED_FULL_ANNUAL_ORIGINALS_NOT_PRESENT_IN_REGISTERED_INPUTS',
            'note': 'eia923.html and instructions PDF are metadata/methods, not annual raw generation tables.'},
        'definition': 'Net generation in MWh, not gross generation, electricity sales or site self-consumption. No inference of zero from absent extract rows.',
        'numeric_comparison_rule': 'Require three pre and two post years complete/comparable; ratio only if pre mean >0. Plant series remains conditional on time-valid facility/asset relations.'}
    archive = ROOT / 'inputs/public/identity_preflight_2026-10-25/eia8602017.zip'
    with zipfile.ZipFile(archive) as z:
        coverage['eia8602017_archive_members'] = [i.filename for i in z.infolist()]
    write(out / 'EIA_COVERAGE.json', coverage)
    public = ROOT / 'inputs/public/mallard_evidence_2026-10-26'
    from pypdf import PdfReader
    epa = PdfReader(public / 'epa_cair_finaltech01.pdf')
    matching_pages = [i for i, p in enumerate(epa.pages) if '55013' in (p.extract_text() or '')]
    assert matching_pages == [140]
    page = epa.pages[140].extract_text()
    assert '265128270' in page and 'MALLARD RIDGE' in page
    dnr = PdfReader(public / 'dnr_MallardProjectSummary.pdf')
    assert '265089770' in dnr.pages[0].extract_text() and '265128270-P20' in dnr.pages[1].extract_text()
    snippets = {'epa': {'path': str((public/'epa_cair_finaltech01.pdf').relative_to(ROOT)), 'sha256': sha(public/'epa_cair_finaltech01.pdf'),
               'pdf_page_one_based': 141, 'printed_page': 'F-46', 'context_pdf_page': 28, 'context_printed_page': '23',
               'ids': {'ORIS_ID': '55013', 'NEI_Plant_ID': '265128270', 'name': 'WASTE MANAGEMENT - MALLARD RIDGE'},
               'partial_site': 'yes (visually read); EGU record count is not generator inventory count',
               'interpretation': '2001 NEI-to-IPM/NEEDS historical mapping in a 4 March2005 publication; not current supply or full asset coverage'},
        'dnr': {'path': str((public/'dnr_MallardProjectSummary.pdf').relative_to(ROOT)), 'sha256': sha(public/'dnr_MallardProjectSummary.pdf'),
               'facility_pdf_page': 1, 'permit_pdf_page': 2, 'document_date': '2022-11-30',
               'ids': {'landfill_FID':'265089770','air_permit':'265128270-P20','license':'3244'},
               'address': 'W8470 State Highway11; Town of Darien, Walworth County, Wisconsin',
               'interpretation':'Facility identity and permit context; expansion configurations do not establish operation'}}
    for key, filename, title in [
        ('waga_delivery','waga_delivery.html','Delivery of two cryogenic distillation columns to Air Liquide'),
        ('waga_acceptance','waga_acceptance.html','First cryogenic distillation module sold to Air Liquide passes acceptance testing')]:
        html = (public / filename).read_text(encoding='utf-8')
        parser = VisibleText(); parser.feed(html)
        lines = [' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip()]
        start = lines.index(title)
        tail = lines[start:]
        end = next((i for i, line in enumerate(tail) if line in {'Last news', 'All News on RNG'}), len(tail))
        article = tail[:end]
        required = ['March 2022', 'Mallard'] if key=='waga_delivery' else ['January', 'already producing RNG', 'injecting it directly']
        assert all(any(term in line for line in article) for term in required)
        pub = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        snippets[key] = {'path': str((public/filename).relative_to(ROOT)), 'sha256': sha(public/filename),
                         'title': title, 'visible_date': next(line for line in article if re.search(r'Apr\s+\d+,\s+2023', line)),
                         'metadata_date_published': pub.group(1) if pub else None,
                         'article_blocks_with_relevant_terms': [{'block_one_based': i+1, 'terms_found': [term for term in required if term in line]} for i,line in enumerate(article) if any(term in line for term in required)],
                         'organisation_group': 'WAGA_ENERGY_ONE_SUPPLIER', 'human_review_status':'PENDING'}
    write(out / 'PUBLIC_SOURCE_READ_RECORD.json', snippets)
    card = ['Mallard关键原件入口（待本人核对，不代标人工已核验）', '']
    for label, obj in [('EIA GEN1',gen1),('LMOP登记',reg)]:
        card.extend([label, obj['absolute_path'], f"工作表={obj['sheet']}；表头Excel第{obj['header_excel_row']}行；筛选={obj['filters']}"])
        for row in obj['matched_records']:
            card.append(f"Excel行={row['excel_row_one_based']}；worksheet零基行={row['worksheet_row_zero_based']}；跳过表头后的data零基行={row['data_row_zero_based']}")
            for field, cell in row['cells'].items():
                card.append(f"  {field}: {cell['cell']} = {cell['value']} (code列索引{cell.get('code_column_zero_based')})")
        card.append('')
    card.extend(['PDF：'+str((public/'epa_cair_finaltech01.pdf').resolve())+'，第141页/印刷F-46，ORIS55013所在行；先看Plant ID/ORIS ID表头。',
                 'PDF：'+str((public/'dnr_MallardProjectSummary.pdf').resolve())+'，第1页FID与地址，第2页空气许可。',
                 '复核状态：自动抽取已完成；助手已读相关原页/原文；用户人工复核仍待完成。'])
    (out/'HUMAN_REVIEW_ENTRIES.txt').write_text('\n'.join(card),encoding='utf-8')
    checks = {'gen1_found_by_keys_not_row':gen1['matched_count']==1,'no_original_modified':all(sha(ROOT/p)==h for p,h in before.items()),
              'lmop1676_two_projects':reg['matched_count']==2,'all_four_public_originals_present':all((public/f).is_file() for f in ['epa_cair_finaltech01.pdf','dnr_MallardProjectSummary.pdf','waga_delivery.html','waga_acceptance.html']),
              'source_ids_and_event_terms_read':True,'no_human_verified_flag':all(obj['human_review_status'].startswith('PENDING') for obj in [gen1,reg])}
    write(out/'AUDIT_RECORD.json',{'utc':datetime.now(timezone.utc).isoformat(),'command':[sys.executable,*sys.argv],
          'code_sha256':sha(Path(__file__)),'source_hashes':before,'checks':checks,'human_hours':None})
    assert all(checks.values()),checks
    print(json.dumps({'output':str(out),'gen1_excel_row':gen1['matched_records'][0]['excel_row_one_based'],
                     'gen1_fields':{k:v['cell']+'='+str(v['value']) for k,v in gen1['matched_records'][0]['cells'].items() if k in ['Operating Month','Operating Year','Retirement Month','Retirement Year']},
                     'lmop_rows':[r['excel_row_one_based'] for r in reg['matched_records']], 'checks':checks},ensure_ascii=False))


if __name__ == '__main__':
    main()

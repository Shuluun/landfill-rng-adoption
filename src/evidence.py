"""Read-only sources and typed evidence; raw files stay in place."""
from pathlib import Path
import hashlib, json
import openpyxl
from .linkage import text


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def public_supplement(root, manifest_path, relation_doc):
    """Attach curated, located claims; retain unresolved electric-plant supply edge."""
    doc = load(root / manifest_path)
    downloads = load(root / doc['download_manifest'])['records']
    sources = {r['id']: r for r in downloads if r.get('sha256')}
    claims = {r['id']: r for r in doc['claims']}
    assert all(c['source_id'] in sources for c in claims.values()), 'A claim requires a materialized original'
    files = [root / manifest_path, root / doc['download_manifest']]
    for source in sources.values():
        path = (root / source['path']).resolve()
        assert path.is_relative_to(root) and sha(path) == source['sha256']
        files.append(path)
    for rel in doc['relations']:
        evidence = []
        for claim_id in rel['claim_ids']:
            claim = claims[claim_id]
            evidence.append({'claim_id': claim_id, 'location': claim['location'],
                             'support_scope': claim['supports'], 'limitations': claim['does_not_support'],
                             'source': sources[claim['source_id']]})
        relation_doc['relations'].append({**rel, 'valid_from': None, 'valid_to': None,
            'valid_time_note': rel['valid_time_scope'], 'evidence': evidence,
            'review_status': 'ASSISTANT_READ_ORIGINAL_PENDING_HUMAN',
            'reason': 'Curated source-specific claim; no uninterrupted validity interval inferred.'})
    return doc, files


def source_rows(path, sheet, header_row, start, end):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    headers = [text(v) for v in next(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))]
    result = []
    for n, row in enumerate(ws.iter_rows(min_row=start, max_row=end, values_only=True), start):
        result.append((n, dict(zip(headers, row))))
    wb.close()
    return result


def locate_keyed_records(path, sheet, filters, fields):
    """Discover headers and scan keys; previous Excel row numbers are not inputs."""
    from datetime import datetime, date
    from decimal import Decimal, InvalidOperation
    from openpyxl.utils import get_column_letter

    def matches(field, value, target):
        if field in {'Plant ID', 'Plant Code', 'Landfill ID'}:
            try:
                return Decimal(str(value).strip()) == Decimal(str(target).strip())
            except InvalidOperation:
                return False
        return str(value).strip() == str(target).strip()

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        wb.close()
        raise ValueError(f'Missing source sheet {sheet}')
    ws = wb[sheet]
    header_row = None
    for n, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), 1):
        headers = {text(v): i for i, v in enumerate(row) if text(v)}
        if set(filters).issubset(headers):
            header_row = n
            break
    if header_row is None:
        wb.close()
        raise ValueError('Header not identified; do not infer an absent record')
    rows = []
    scanned = 0
    primary = next(iter(filters))
    for excel_row, values in enumerate(ws.iter_rows(min_row=header_row+1, values_only=True), header_row+1):
        if values[headers[primary]] is None:
            continue
        scanned += 1
        if not all(matches(key, values[headers[key]], target) for key, target in filters.items()):
            continue
        cells = {}
        for field in fields:
            if field not in headers:
                cells[field] = {'source_field_status': 'NOT_A_COLUMN_IN_THIS_SHEET', 'cell': None, 'value': None}
                continue
            index = headers[field]
            value = values[index]
            cells[field] = {'original_field_name': field, 'cell': f'{get_column_letter(index+1)}{excel_row}',
                            'header_cell': f'{get_column_letter(index+1)}{header_row}',
                            'excel_column_one_based': index+1, 'code_column_zero_based': index,
                            'value': value.isoformat() if isinstance(value, (datetime, date)) else value,
                            'python_read_type': type(value).__name__,
                            'source_field_status': 'PRESENT_BLANK' if value is None or isinstance(value, str) and not value.strip() else 'PRESENT_WITH_VALUE'}
        rows.append({'excel_row_one_based': excel_row, 'worksheet_row_zero_based': excel_row-1,
                     'data_row_zero_based': excel_row-header_row-1, 'cells': cells})
    result = {'absolute_path': str(path.resolve()), 'sha256': sha(path), 'sheet': sheet, 'header_excel_row': header_row,
              'first_data_excel_row': header_row+1, 'filters': filters, 'scanned_records_with_primary_key': scanned,
              'matched_records': rows, 'matched_count': len(rows),
              'extraction_status': 'AUTOMATIC_KEY_SCAN_ORIGINAL', 'assistant_original_read_status': 'REQUIRES_EXPLICIT_REVIEW',
              'human_review_status': 'PENDING_NOT_MARKED_VERIFIED'}
    wb.close()
    return result


def original_case_records(root, paths, freeze, plant_source, inventory_source, fid, pid, registry_rows, event, plant2017):
    """Use existing row locators, then verify IDs in the immutable originals."""
    raw_lmop = root / freeze['input_path']
    raw_inventory = root / inventory_source['local_path']
    expected_registry = [r for r in registry_rows if r['Landfill ID'] == fid]
    locators = sorted(r['excel_row'] for r in expected_registry)
    actual = source_rows(raw_lmop, 'LMOP Database', 1, min(locators), max(locators))
    actual = [(n, r) for n, r in actual if n in locators]
    assert len(actual) == len(locators) and all(int(r['Landfill ID']) == fid for _, r in actual)
    by_row = {r['excel_row']: r for r in expected_registry}
    for n, r in actual:
        prior = by_row[n]
        assert str(r['Project ID']) == prior['Project ID']
        for key in ['Project Start Date', 'Project Shutdown Date']:
            value = r[key].isoformat() if r[key] is not None else None
            assert value == prior[key], (n, key)
    plant_record = None
    if plant2017 is not None:
        original = root / plant_source['local_original']
        row = plant2017['source_excel_row']
        plant_record = source_rows(original, 'Plant', 2, row, row)[0][1]
        for key in ['Plant Code', 'Plant Name', 'Street Address', 'City', 'County', 'Zip', 'Latitude', 'Longitude']:
            assert plant_record[key] == plant2017[key], (key, plant_record.get(key), plant2017.get(key))
    units = []
    projection_omissions = []
    sheets = sorted({r['sheet'] for r in event['reported_unit_rows']})
    for sheet in sheets:
        expected = {r['source_row']: r for r in event['reported_unit_rows'] if r['sheet'] == sheet}
        rows = source_rows(raw_inventory, sheet, 3, min(expected), max(expected))
        for n, r in rows:
            if n not in expected:
                continue
            prior = expected[n]
            assert int(r['Plant ID']) == pid and str(r['Generator ID']) == prior['id']
            assert r['Energy Source Code'] == prior['fuel']
            for source_key, prior_key in [('Operating Year', 'operating_year'), ('Operating Month', 'operating_month'),
                                          ('Retirement Year', 'retirement_year'), ('Retirement Month', 'retirement_month')]:
                if prior_key in prior:
                    assert r.get(source_key) == prior[prior_key], (n, source_key)
                else:
                    projection_omissions.append({'source_row': n, 'generator_id': str(r['Generator ID']),
                                                 'field_absent_from_legacy_projection': prior_key,
                                                 'original_field': source_key, 'original_value': r.get(source_key)})
            units.append((sheet, n, r))
    assert len(units) == len(event['reported_unit_rows'])
    return actual, plant_record, units, projection_omissions


def pointer(root, path, sheet, rows, vintage):
    return {'path': str(path.relative_to(root)), 'sha256': sha(path), 'sheet': sheet, 'rows': rows, 'record_vintage': vintage}


def relations(root, fid, pid, site, target, registry, units, plant2017, source, inventory_source, freeze):
    e_reg = pointer(root, root / freeze['input_path'], 'LMOP Database', [n for n, _ in registry], 'September 2024')
    e_unit_sources = [pointer(root, root / inventory_source['local_path'], sheet,
                             [n for s, n, _ in units if s == sheet], 'September 2026 preliminary')
                      for sheet in sorted({s for s, _, _ in units})]
    e_plant = pointer(root, root / source['local_original'], 'Plant', [plant2017['source_excel_row']], '2017 annual') if plant2017 else None
    rows = []

    def add(kind, left, right, status, sources, reason, **extra):
        rows.append({'relation_type': kind, 'from': left, 'to': right, 'status': status,
                     'valid_from': None, 'valid_to': None,
                     'valid_time_note': 'No continuous effective interval is inferred from snapshots or event dates.',
                     'evidence': sources, 'reason': reason, 'review_status': 'SOURCE_AUDIT_PENDING_HUMAN_RELATION_REVIEW', **extra})

    if e_plant:
        add('SAME_ENTITY_RECORD', f'EIA860:2017:Plant{pid}', f'EIA860M:2026-09:Plant{pid}',
            'SAME_REPORTED_PLANT_IDENTIFIER', [e_plant, *e_unit_sources], 'Same reported EIA plant identifier; this is not a landfill/plant identity or uninterrupted-continuity assertion.')
    location_status = 'REPORTED_ADDRESS_COHERENCE_EVENT_YEAR_UNRESOLVED' if target['street_equal'] and target['zip_equal'] else 'UNRESOLVED_SPATIAL_LEAD_ONLY'
    add('COLOCATED', f'LMOP:Landfill{fid}', f'EIA:Plant{pid}', location_status,
        [p for p in [e_reg, e_plant, *e_unit_sources] if p], 'Address and/or reported coordinates provide a location lead. Event-year co-location and gas supply need separate evidence.',
        distance_km=target['distance_km'], city_disagreement=not target['city_equal'])
    rng_year = min(r['Project Start Date'].year for _, r in registry if r['Project Type Category'] == 'Renewable Natural Gas')
    add('GAS_SUPPLY', f'LMOP:Landfill{fid}', f'EIA:Plant{pid}', f'UNRESOLVED_AT_{rng_year}_EVENT',
        [p for p in [e_reg, e_plant, *e_unit_sources] if p], 'Name, proximity, fuel and compatible dates cannot alone establish the physical event-year supply edge.')
    for sheet, n, r in units:
        generator = str(r['Generator ID'])
        add('PLANT_CONTAINS_GENERATOR', f'EIA:Plant{pid}', f'EIA:Plant{pid}:Generator{generator}',
            'REPORTED_IN_RETROSPECTIVE_INVENTORY',
            [pointer(root, root / inventory_source['local_path'], sheet, [n], 'September 2026 preliminary')],
            'Reported plant membership; operating/retirement months remain separate events, not a complete effective-interval measurement.',
            reported_original_operation_month=f"{int(r['Operating Year']):04d}-{int(r['Operating Month']):02d}",
            reported_retirement_month=f"{int(r['Retirement Year']):04d}-{int(r['Retirement Month']):02d}" if r.get('Retirement Year') else None)
    for _, r in registry:
        if r['Project Type Category'] == 'Electricity':
            add('PROJECT_ASSET_ASSOCIATION', f"LMOP:Landfill{fid}:Project{r['Project ID']}", f'EIA:Plant{pid}:listed_generator_set',
                'UNRESOLVED_MEMBERSHIP', [e_reg, *e_unit_sources], 'Project/expansion-to-generator membership remains unresolved; no whole-plant generation is allocated to each project.')
    return {'landfill_id': fid, 'provisional_plant_id': pid, 'relations': rows, 'site_pathway': 'UNDETERMINED',
            'generation_assigned_to_landfill': None,
            'reason': 'Physical supply, event-year validity and project/asset completeness still require verification.'}, [p for p in [e_reg, e_plant, *e_unit_sources] if p]

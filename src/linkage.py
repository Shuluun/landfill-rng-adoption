"""Transparent candidate rules extracted from the working case audit."""
from difflib import SequenceMatcher
import math, re, unicodedata
STOP = {'and', 'inc', 'landfills', 'of', 'slf', 'ltd', 'incorporated', 'rdf', 'llc', 'the', 'landfill'}


def text(value):
    if value is None or isinstance(value, float) and not math.isfinite(value):
        return ''
    return str(value).strip()


def tokens(value):
    value = unicodedata.normalize('NFKD', text(value)).encode('ascii', 'ignore').decode().lower()
    return re.findall(r'[a-z0-9]+', value)


def name_key(value):
    return ' '.join(word for word in tokens(value) if word not in STOP)


def street_key(value):
    aliases = {'road': 'rd', 'street': 'st', 'avenue': 'ave', 'boulevard': 'blvd',
               'north': 'n', 'south': 's', 'east': 'e', 'west': 'w'}
    return ' '.join(aliases.get(word, word) for word in tokens(value))


def zip_key(value):
    match = re.search(r'\d{5}', text(value))
    return match.group(0) if match else ''


def coordinates(record):
    try:
        lat, lon = float(record['Latitude']), float(record['Longitude'])
        return (lat, lon) if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180 else None
    except (TypeError, ValueError, KeyError):
        return None


def haversine(a, b):
    # Same formula/radius as the existing check_geographic_candidates.py.
    a1, o1, a2, o2 = map(math.radians, [*a, *b])
    v = math.sin((a2-a1)/2)**2 + math.cos(a1)*math.cos(a2)*math.sin((o2-o1)/2)**2
    return 6371.0088 * 2 * math.atan2(math.sqrt(v), math.sqrt(max(0, 1-v)))


def candidate_features(site, plant):
    a, b = name_key(site['Landfill Name']), name_key(plant['Plant Name'])
    aliases = plant.get('name_aliases', [plant['Plant Name']])
    score = max((SequenceMatcher(None, a, name_key(v), autojunk=False).ratio() if a and name_key(v) else 0.0) for v in aliases)
    s_coord, p_coord = coordinates(site), coordinates(plant)
    distance = haversine(s_coord, p_coord) if s_coord is not None and p_coord is not None else None
    street = street_key(site['Physical Address'])
    zipcode = zip_key(site['Zip Code'])
    return {
        'plant_code': int(plant['Plant Code']), 'plant_name': plant['Plant Name'],
        'state': plant['State'], 'source_plant_row': plant['source_excel_row'] if plant.get('source_kind', 'plant2017') == 'plant2017' else None,
        'source_kind': plant.get('source_kind', 'plant2017'),
        'source_records': plant.get('source_records', [{'sheet': 'Plant', 'row': plant['source_excel_row']}]),
        'name_score': round(score, 8), 'distance_km': round(distance, 6) if distance is not None else None,
        'coordinate_available': p_coord is not None,
        'same_state': plant['State'] == site['State'],
        'street_equal': bool(street) and street == street_key(plant['Street Address']),
        'zip_equal': bool(zipcode) and zipcode == zip_key(plant['Zip']),
        'county_equal': bool(text(site['County'])) and tokens(site['County']) == tokens(plant['County']),
        'city_equal': bool(text(site['City'])) and tokens(site['City']) == tokens(plant['City']),
        'plant_street': plant['Street Address'], 'plant_city': plant['City'],
        'plant_county': plant['County'], 'plant_zip': text(plant['Zip']),
        'link_status': 'CANDIDATE_ONLY',
    }


def joint_tier(row, config):
    if row['street_equal'] and row['zip_equal']:
        return 0
    if row['county_equal'] and row['distance_km'] is not None and row['distance_km'] <= config['maximum_distance_km']:
        return 1
    if row['name_score'] >= config['minimum_name_score']:
        return 2
    return 3


def retrieve(features, config):
    pool = [r for r in features if r['same_state']]
    by_name = sorted([r for r in pool if r['name_score'] >= config['minimum_name_score']], key=lambda r: (-r['name_score'], r['plant_code']))[:config['name_top_k']]
    by_distance = sorted([r for r in pool if r['distance_km'] is not None and r['distance_km'] <= config['maximum_distance_km']], key=lambda r: (r['distance_km'], r['plant_code']))[:config['distance_top_k']]
    by_joint = sorted([r for r in pool if joint_tier(r, config) < 3],
                      key=lambda r: (joint_tier(r, config), -r['name_score'], r['distance_km'] if r['distance_km'] is not None else math.inf, r['plant_code']))[:config['joint_top_k']]
    return {'name': by_name, 'distance': by_distance, 'joint': by_joint}


def inventory_catalogue(records):
    """Derive candidates from the existing staged inventory, retaining provenance.

    Fuel-limited coverage is explicit. Conflicting coordinate variants are kept
    as variants and not averaged or selected by whichever is closest.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for row in records:
        if row['Energy Source Code'] == 'LFG':
            groups[int(row['Plant ID'])].append(row)
    result = []
    for pid, rows in sorted(groups.items()):
        names = sorted({text(r['Plant Name']) for r in rows if text(r['Plant Name'])})
        states = sorted({text(r['Plant State']) for r in rows})
        counties = sorted({text(r['County']) for r in rows if text(r['County'])})
        assert len(states) == 1, (pid, states)
        variants = sorted({coordinates(r) for r in rows if coordinates(r) is not None})
        point = variants[0] if len(variants) == 1 else (None, None)
        sources = [{'sheet': r['source_sheet'], 'row': r['source_excel_row'], 'generator_id': str(r['Generator ID'])} for r in rows]
        result.append({'Plant Code': pid, 'Plant Name': names[0], 'name_aliases': names,
                       'Street Address': None, 'City': None, 'State': states[0], 'Zip': None,
                       'County': counties[0] if len(counties) == 1 else None,
                       'Latitude': point[0], 'Longitude': point[1], 'coordinate_variants': variants,
                       'source_excel_row': min(r['source_excel_row'] for r in rows),
                       'source_kind': 'inventory2026_lfg_staged', 'source_records': sources})
    return result

"""Fetch exact public URLs; Mallard defaults or a bounded project source list."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import urllib.request
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ('EPA_CAIR_2005', 'https://archive.epa.gov/airmarkets/programs/cair/web/pdf/finaltech01.pdf', 'epa_cair_finaltech01.pdf'),
    ('DNR_MALLARD_2022', 'https://dnr.wisconsin.gov/sites/default/files/topic/Landfills/comment/MallardProjectSummary.pdf', 'dnr_MallardProjectSummary.pdf'),
    ('WAGA_DELIVERY', 'https://waga-energy.com/en-us/news/delivery-of-two-cryogenic-distillation-columns-to-air-liquide/', 'waga_delivery.html'),
    ('WAGA_ACCEPTANCE', 'https://waga-energy.com/en-us/news/first-cryogenic-distillation-module-sold-to-air-liquide-passes-acceptance-testing/', 'waga_acceptance.html'),
]


def main():
    started = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--source-list', help='Existing project JSON with exact sources and output_directory')
    args = parser.parse_args()
    sources = SOURCES
    out = ROOT / 'inputs/public/mallard_evidence_2026-10-26'
    source_list_path = None
    byte_limits = {}
    if args.source_list:
        source_list_path = (ROOT / args.source_list).resolve()
        assert source_list_path.is_relative_to(ROOT)
        config = json.loads(source_list_path.read_text(encoding='utf-8'))
        out = (ROOT / config['output_directory']).resolve()
        assert out.is_relative_to(ROOT / 'inputs/public')
        sources = [(r['id'], r['url'], r['filename']) for r in config['sources']]
        byte_limits = {r['id']: r.get('maximum_bytes', 20000000) for r in config['sources']}
        assert all(0 < n <= 60000000 for n in byte_limits.values())
        assert len(sources) <= 6
    out.mkdir(parents=True, exist_ok=True)
    record_path = out / ('DOWNLOAD_ATTEMPT_' + args.attempt + '.json')
    if record_path.exists():
        raise FileExistsError(record_path)
    records = []
    for sid, url, filename in sources:
        assert url.startswith('https://') and Path(filename).name == filename
        path = out / filename
        maximum_bytes = byte_limits.get(sid, 20000000)
        row = {'id': sid, 'requested_url': url, 'retrieved_utc': datetime.now(timezone.utc).isoformat(), 'path': str(path.relative_to(ROOT))}
        try:
            if path.exists():
                payload = path.read_bytes()
                row.update(status='EXISTING_ORIGINAL_REUSED_NOT_OVERWRITTEN', bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            else:
                request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research source verification)'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = response.read(maximum_bytes+1)
                    if len(payload) > maximum_bytes:
                        raise ValueError(f'Scoped single-file limit exceeded: {maximum_bytes}')
                    if filename.endswith('.pdf') and not payload.startswith(b'%PDF'):
                        raise ValueError('Response is not an original PDF')
                    row.update(status='DOWNLOADED', http_status=response.status, final_url=response.url,
                               content_type=response.headers.get('Content-Type'), last_modified=response.headers.get('Last-Modified'),
                               bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
                path.write_bytes(payload)
        except Exception as exc:
            row.update(status='FAILED', error_type=type(exc).__name__, error=str(exc), original_saved=False)
        records.append(row)
    record_path.write_text(json.dumps({'command_scope': 'Exact bounded public source list; no external links followed',
        'command': [sys.executable,*sys.argv], 'python':sys.version,
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_list':str(source_list_path.relative_to(ROOT)) if source_list_path else 'Mallard defaults',
        'source_list_sha256':hashlib.sha256(source_list_path.read_bytes()).hexdigest() if source_list_path else None,
        'timeout_seconds_per_file':15,'default_maximum_bytes_per_file':20000000,'explicit_byte_limits':byte_limits,
        'elapsed_tool_wall_seconds':time.perf_counter()-started,'human_hours_used':None,'records': records}, indent=2), encoding='utf-8')
    print(json.dumps({'record': str(record_path), 'results': [{'id': r['id'], 'status': r['status'], 'bytes': r.get('bytes'), 'error': r.get('error')} for r in records]}))


if __name__ == '__main__':
    main()

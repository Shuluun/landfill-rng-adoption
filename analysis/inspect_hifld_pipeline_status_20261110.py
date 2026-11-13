"""Inspect the HIFLD pipeline shapefile attribute table (.dbf) for the Status field.

Read-only. Dumps field names, the Status value distribution, and the geometry
record count so the Phase-3 endogeneity robustness can decide what to drop.

DBF layout (dBASE III): bytes 0..31 header, field descriptors at 32 (32 bytes each,
name at offset 0, type at 11, length at 16), 0x0D terminator, then fixed-width records
with a leading deletion flag.
"""
import argparse, datetime as dt, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBF = ROOT / 'inputs/public/hifld_natural_gas_pipelines_20261104/shapefile_extracted/natural-gas-interstate-and-intrastate-pipelines.dbf'
SHP = ROOT / 'inputs/public/hifld_natural_gas_pipelines_20261104/shapefile_extracted/natural-gas-interstate-and-intrastate-pipelines.shp'


def read_dbf(path):
    b = Path(path).read_bytes()
    nrec = int.from_bytes(b[4:8], 'little')
    hsize = int.from_bytes(b[8:10], 'little')
    rsize = int.from_bytes(b[10:12], 'little')
    fields = []
    off = 32
    while b[off] != 0x0D:
        name = b[off:off + 11].split(b'\x00')[0].decode('ascii', 'replace')
        ftype = chr(b[off + 11])
        flen = b[off + 16]
        fields.append((name, ftype, flen, off))
        off += 32
    rows = []
    for i in range(nrec):
        rec = b[hsize + i * rsize: hsize + (i + 1) * rsize]
        if rec[0] in (0x2A, 0x20):  # not deleted
            row = {}
            pos = 1
            for name, ftype, flen, _ in fields:
                raw = rec[pos:pos + flen].decode('latin-1', 'replace').strip()
                row[name] = raw
                pos += flen
            rows.append(row)
    return fields, nrec, rsize, rows


def count_shp_records(path):
    b = Path(path).read_bytes()
    # count 4-byte big-endian record headers until EOF
    off = 100
    n = 0
    while off + 8 <= len(b):
        _, clen = (int.from_bytes(b[off:off + 4], 'big'), int.from_bytes(b[off + 4:off + 8], 'big'))
        off += 8 + 2 * clen
        n += 1
    return n


def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'outputs' / 'inspect_hifld_status'
    out.mkdir(parents=True, exist_ok=True)

    fields, nrec, rsize, rows = read_dbf(DBF)
    n_shp = count_shp_records(SHP)

    from collections import Counter
    status_counter = Counter(r.get('Status', '<missing>') for r in rows)
    status_norm = Counter()
    for k, v in status_counter.items():
        status_norm[k.strip().title()] += v

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'dbf': str(DBF),
        'n_records_dbf': nrec,
        'record_size': rsize,
        'n_records_shp': n_shp,
        'fields': [{'name': f[0], 'type': f[1], 'length': f[2]} for f in fields],
        'status_distribution_raw': dict(status_counter),
        'status_distribution_normalized': dict(status_norm),
    }
    (out / 'hifld_status_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

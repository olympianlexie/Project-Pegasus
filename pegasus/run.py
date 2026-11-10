"""One command to rebuild everything:

    python -m pegasus.run                      # newest exports in data/
    python -m pegasus.run --raw path.xlsx --tableau path.xlsx
    python -m pegasus.run --skip-kmz           # faster: map + Excel only
"""
from __future__ import annotations

import argparse
import sys
import time

from . import build_map, config, export_kmz, pipeline, relocate, report_excel, validate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rebuild the Project Pegasus map, KMZ files and relocation plan.")
    ap.add_argument("--raw", help="raw port utilization export (.xlsx); default: newest match in data/")
    ap.add_argument("--tableau", help="Tableau crosstab export (.xlsx); default: newest match in data/")
    ap.add_argument("--out", default=str(config.OUTPUT_DIR), help="output folder (default: output/)")
    ap.add_argument("--skip-kmz", action="store_true", help="don't build the Google Earth files")
    ap.add_argument("--skip-excel", action="store_true", help="don't build the Excel workbooks")
    args = ap.parse_args(argv)

    from pathlib import Path
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    def step(msg):
        print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)

    step("reading and reconciling data (first read of a new export takes ~30 s)")
    ds = pipeline.build(args.raw, args.tableau)
    step("planning relocations")
    reloc = relocate.plan(ds)

    text, fails = validate.report(ds, reloc)
    print(text)
    (out / "validation_report.txt").write_text(text, encoding="utf-8")

    step("building map")
    built = [build_map.build(ds, reloc, out / "pegasus_map.html")]
    if not args.skip_excel:
        step("writing Excel workbooks")
        built.append(report_excel.write_relocation_workbook(ds, reloc, out / "Pegasus_Relocation_Plan.xlsx"))
        built.append(report_excel.write_nap_workbook(ds, out / "Pegasus_NAP_Table.xlsx"))
    if not args.skip_kmz:
        step("writing KMZ files")
        built += export_kmz.export(ds, reloc, out / "google_earth")
    step("done")
    print("\nOutputs:")
    for p in built:
        print(f"  {p}  ({p.stat().st_size / 1e6:.1f} MB)")
    print(f"  {out / 'validation_report.txt'}")
    if fails:
        print(f"\nWARNING: {len(fails)} validation check(s) failed; see the report above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

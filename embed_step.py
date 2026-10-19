#!/usr/bin/env python3
"""Embed one radial QIM bit per STEP topological vertex."""

import argparse
import json
from pathlib import Path
import sys

from qim_step import StepDocument, WARNING, choose_bits, embed, ensure_new_paths, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=WARNING)
    parser.add_argument("input", type=Path, help="Source .stp/.step file")
    parser.add_argument("output", type=Path, help="Output .stp/.step file")
    parser.add_argument("--delta", type=float, required=True, help="Spacing between adjacent QIM levels, in model units")
    parser.add_argument("--mode", choices=("0", "1", "random"), default="random", help="Default bit for each vertex (default: random)")
    parser.add_argument("--seed", type=int, default=0, help="Random seed (default: 0)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--bits", help="Exact bit string, ordered by increasing VERTEX_POINT entity ID")
    group.add_argument("--bits-file", type=Path, help='JSON overrides, e.g. {"1556": 0, "1557": 1, "1558": "random"}')
    parser.add_argument("--center", type=float, nargs=3, metavar=("X", "Y", "Z"), help="Fixed center (default: original vertex coordinate mean)")
    parser.add_argument("--report", type=Path, help="Write original bits and vertex displacement report to JSON")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        ensure_new_paths(args.input, [args.output, args.report], args.overwrite)
        if args.bits_file and args.bits_file.resolve() in {p.resolve() for p in (args.output, args.report) if p}:
            raise ValueError("Outputs must not overwrite bits-file.")
        document = StepDocument.read(args.input)
        overrides = json.loads(args.bits_file.read_text(encoding="utf-8")) if args.bits_file else None
        bits = choose_bits(document.vertices, args.mode, args.seed, args.bits, overrides)
        text, report = embed(document, args.delta, bits, args.center)
        args.output.write_bytes(text.encode("latin-1"))
        if args.report:
            write_json(args.report, report)
        print(f"Embedded {len(bits)} bits into {args.output}")
        print(f"Center: {report['center']}; delta: {args.delta:g}; max displacement: {report['max_displacement']:.9g}")
        print("WARNING: " + WARNING, file=sys.stderr)
    except (OSError, ValueError, OverflowError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

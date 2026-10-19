#!/usr/bin/env python3
"""Decode radial QIM bits from STEP vertex coordinates, without original bits."""

import argparse
from pathlib import Path
import sys

from qim_step import StepDocument, ensure_new_paths, extract, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="Write decoded bits and radii to JSON")
    parser.add_argument("--bits-output", type=Path, help="Write just the bit string to a text file")
    parser.add_argument("--delta", type=float, help="Override QIM spacing, required when metadata is absent")
    parser.add_argument("--center", type=float, nargs=3, metavar=("X", "Y", "Z"), help="Override original fixed center; do not recompute from deformed vertices")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        ensure_new_paths(args.input, [args.output, args.bits_output], args.overwrite)
        report = extract(StepDocument.read(args.input), args.delta, args.center)
        if args.output:
            write_json(args.output, report)
        if args.bits_output:
            args.bits_output.write_text(report["bits"] + "\n", encoding="ascii")
        print(report["bits"])
        print(f"Decoded {report['vertex_count']} bits; off-lattice vertices: {report['off_lattice_count']}", file=sys.stderr)
        if report["off_lattice_count"]:
            print("WARNING: Coordinates are off the QIM lattice; bits are nearest-level estimates.", file=sys.stderr)
            return 1
    except (OSError, ValueError, OverflowError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

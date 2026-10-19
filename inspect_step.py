#!/usr/bin/env python3
"""List STEP vertex IDs, coordinates, and distances to the original vertex mean."""

import argparse
from pathlib import Path

from qim_step import StepDocument, ensure_new_paths, radius, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="Also write vertex information to JSON")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        ensure_new_paths(args.input, [args.output], args.overwrite)
        document = StepDocument.read(args.input)
        center = document.center()
        rows = [{"vertex_id": v.number, "point_id": v.point_id, "xyz": v.xyz,
                 "radius": radius(v.xyz, center)} for v in document.vertices]
        if args.output:
            write_json(args.output, {"vertex_count": len(rows), "center": center, "vertices": rows})
        print(f"Vertices: {len(rows)}; coordinate mean: {center}")
        for row in rows:
            print(f"#{row['vertex_id']}: xyz={row['xyz']}, radius={row['radius']:.12g}")
    except (OSError, ValueError, OverflowError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

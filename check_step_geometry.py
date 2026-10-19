#!/usr/bin/env python3
"""Optional OpenCascade B-rep check; install requirements-cad.txt first."""

import argparse
import json
from pathlib import Path

from qim_step import ensure_new_paths


def inspect(path):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise ValueError(f"OpenCascade could not read {path}: {status}")
    transferred = reader.TransferRoots()
    shape = reader.OneShape()
    if not transferred or shape.IsNull():
        raise ValueError(f"OpenCascade could not transfer a shape from {path}.")
    vertices = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, vertices)
    return {
        "file": str(path), "transferred_roots": transferred,
        "unique_topological_vertices": vertices.Extent(),
        "brep_valid_after_import": BRepCheck_Analyzer(shape).IsValid(),
        "note": "STEP import may heal geometry; this does not verify watermark survival after CAD re-export.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        for path in args.input:
            ensure_new_paths(path, [args.output], args.overwrite)
        results = [inspect(path) for path in args.input]
    except ImportError:
        parser.exit(2, "Install optional dependencies: python -m pip install -r requirements-cad.txt\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    text = json.dumps(results, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if all(row["brep_valid_after_import"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

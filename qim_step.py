"""Radial QIM on STEP VERTEX_POINT coordinates (Python standard library only).

This is a coordinate watermark experiment, not a CAD geometry healing tool.
Moving vertices independently does not update their incident curves/surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re


SCHEME = "radial-parity-qim-v1"
WARNING = (
    "Vertex coordinates are changed independently; edge curves and surfaces are "
    "not rebuilt. The resulting B-rep may be geometrically invalid."
)
_TOKENS = re.compile(r"/\*.*?\*/|'(?:[^']|'')*'|#\d+\s*=|;", re.S)
_COMMENTS_OR_STRINGS = re.compile(r"/\*.*?\*/|'(?:[^']|'')*'", re.S)
_NAME = r"'(?:[^']|'')*'"
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_VERTEX = re.compile(rf"\s*VERTEX_POINT\s*\(\s*({_NAME})\s*,\s*#(\d+)\s*\)\s*", re.I)
_POINT = re.compile(
    rf"\s*CARTESIAN_POINT\s*\(\s*{_NAME}\s*,\s*\(\s*({_NUMBER})\s*,"
    rf"\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)\s*\)\s*", re.I
)
_METADATA = re.compile(r"/\* QIM_RADIAL_V1 (\{[^\r\n]*\}) \*/")


def _uncomment(text: str) -> str:
    return _COMMENTS_OR_STRINGS.sub(
        lambda m: " " if m[0].startswith("/*") else m[0], text
    )


@dataclass(frozen=True)
class Entity:
    number: int
    start: int
    end: int
    body: str


@dataclass(frozen=True)
class Vertex:
    number: int
    name: str
    point_id: int
    xyz: tuple[float, float, float]


class StepDocument:
    def __init__(self, text: str):
        # Latin-1 round trips arbitrary original STEP bytes without recoding names.
        self.text = text
        clean = _uncomment(text)
        if not clean.lstrip().upper().startswith("ISO-10303-21;"):
            raise ValueError("Input is not an ISO-10303-21 STEP file.")
        if not re.search(r"END-ISO-10303-21\s*;\s*$", clean, re.I):
            raise ValueError("STEP end marker is missing.")
        self.entities: dict[int, Entity] = {}
        current = None
        for token in _TOKENS.finditer(text):
            value = token[0]
            if value.startswith("#"):
                if current is not None:
                    raise ValueError("Unterminated STEP entity.")
                current = (int(value[1:].split("=")[0]), token.start(), token.end())
            elif value == ";" and current is not None:
                number, start, body_start = current
                if number in self.entities:
                    raise ValueError(f"Duplicate STEP entity #{number}.")
                self.entities[number] = Entity(
                    number, start, token.end(), _uncomment(text[body_start:token.start()])
                )
                current = None
        if current is not None:
            raise ValueError("Unterminated STEP entity.")
        for entity in self.entities.values():
            # Assembly placement transforms need world/local coordinate handling.
            if re.match(
                r"\s*(?:MAPPED_ITEM|ITEM_DEFINED_TRANSFORMATION|"
                r"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION)\s*\(",
                entity.body, re.I,
            ):
                raise ValueError("Assembly transforms are unsupported; use a single model coordinate frame.")
        self.vertices = []
        for number, entity in sorted(self.entities.items()):
            match = _VERTEX.fullmatch(entity.body)
            if not match:
                if re.match(r"\s*VERTEX_POINT\b", entity.body, re.I):
                    raise ValueError(f"Unsupported VERTEX_POINT syntax at #{number}.")
                continue
            point_id = int(match[2])
            point = self.entities.get(point_id)
            coords = _POINT.fullmatch(point.body) if point else None
            if coords is None:
                raise ValueError(f"Vertex #{number} needs a direct 3D CARTESIAN_POINT.")
            xyz = tuple(float(x.replace("D", "E").replace("d", "e")) for x in coords.groups())
            if not all(math.isfinite(x) for x in xyz):
                raise ValueError(f"Nonfinite coordinates at vertex #{number}.")
            self.vertices.append(Vertex(number, match[1], point_id, xyz))
        if not self.vertices:
            raise ValueError("No supported 3D VERTEX_POINT entities found.")

    @classmethod
    def read(cls, path: str | Path) -> StepDocument:
        return cls(Path(path).read_bytes().decode("latin-1"))

    def center(self) -> tuple[float, float, float]:
        count = len(self.vertices)
        # Divide before summing to avoid overflow for large finite coordinates.
        return tuple(math.fsum(v.xyz[i] / count for v in self.vertices) for i in range(3))

    def metadata(self) -> dict | None:
        # Only actual comment tokens count: labels may contain lookalike text.
        matches = []
        for token in _TOKENS.finditer(self.text):
            match = _METADATA.fullmatch(token[0])
            if match:
                matches.append(match)
        if len(matches) > 1:
            raise ValueError("Multiple QIM metadata comments found.")
        if not matches:
            return None
        try:
            result = json.loads(matches[0][1])
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid QIM metadata JSON.") from exc
        if not isinstance(result, dict) or result.get("scheme") != SCHEME:
            raise ValueError("Unsupported QIM scheme.")
        return result


def parameters(delta: float, center) -> tuple[float, float, float]:
    if not isinstance(delta, (int, float)) or not math.isfinite(delta) or delta <= 0:
        raise ValueError("delta must be a finite positive number in STEP coordinate units.")
    if not isinstance(center, (list, tuple)) or len(center) != 3:
        raise ValueError("center must contain three finite coordinates.")
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in center):
        raise ValueError("center must contain three finite coordinates.")
    return tuple(center)


def radius(xyz, center) -> float:
    result = math.dist(xyz, center)
    if not math.isfinite(result):
        raise ValueError("Coordinate range is too large for radial QIM.")
    return result


def lattice_index(r: float, delta: float) -> int:
    scaled = r / delta
    if not math.isfinite(scaled) or scaled > 2**45:
        raise ValueError("delta is too small relative to the radius for reliable float quantization.")
    return math.floor(scaled + 0.5)


def quantize(r: float, delta: float, bit: int) -> float:
    if bit not in (0, 1):
        raise ValueError("A bit must be 0 or 1.")
    lattice_index(r, delta)
    # Two parity lattices: L0 = {0, 2Δ, 4Δ, ...}, L1 = {Δ, 3Δ, 5Δ, ...}.
    k = max(0, math.floor((r / delta - bit) / 2 + 0.5))
    result = (2 * k + bit) * delta
    if not math.isfinite(result):
        raise ValueError("Quantized radius overflowed; use smaller coordinates/delta.")
    return result


def choose_bits(vertices: list[Vertex], mode="random", seed=0, bits=None, overrides=None) -> list[int]:
    if mode not in ("0", "1", "random"):
        raise ValueError("mode must be 0, 1, or random.")
    if bits is not None:
        if overrides is not None:
            raise ValueError("Use either an explicit bit string or per-vertex overrides.")
        if not isinstance(bits, str) or len(bits) != len(vertices) or set(bits) - {"0", "1"}:
            raise ValueError(f"bits must contain exactly {len(vertices)} binary digits.")
        return [int(b) for b in bits]
    choices = {}
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("bits-file must be a JSON object of vertex IDs to 0, 1, or random.")
        ids = {v.number for v in vertices}
        for key, value in overrides.items():
            if not re.fullmatch(r"#?[1-9]\d*", str(key)):
                raise ValueError(f"Invalid vertex ID {key!r}.")
            number = int(str(key).lstrip("#"))
            if number not in ids or number in choices:
                raise ValueError(f"Unknown or duplicate vertex ID #{number}.")
            if isinstance(value, bool) or str(value) not in ("0", "1", "random"):
                raise ValueError(f"Vertex #{number}: choose 0, 1, or random.")
            choices[number] = str(value)
    rng = random.Random(seed)
    result = []
    for vertex in vertices:
        choice = choices.get(vertex.number, mode)
        result.append(rng.randrange(2) if choice == "random" else int(choice))
    return result


def embed(document: StepDocument, delta: float, bits: list[int], center=None):
    center = parameters(delta, document.center() if center is None else center)
    if len(bits) != len(document.vertices):
        raise ValueError("One bit is required per VERTEX_POINT.")
    newline = "\r\n" if "\r\n" in document.text else "\n"
    edits = []
    points = []
    rows = []
    next_id = max(document.entities) + 1
    for offset, (vertex, bit) in enumerate(zip(document.vertices, bits)):
        r = radius(vertex.xyz, center)
        target = quantize(r, delta, bit)
        if r == 0:
            xyz = (center[0] + target, center[1], center[2])
        else:
            xyz = tuple(c + ((x - c) / r) * target for x, c in zip(vertex.xyz, center))
        if not all(math.isfinite(x) for x in xyz):
            raise ValueError("Embedded coordinate overflow.")
        new_id = next_id + offset
        # A fresh point prevents moving a shared curve control point or axis origin.
        entity = document.entities[vertex.number]
        edits.append((entity.start, entity.end, f"#{vertex.number}=VERTEX_POINT({vertex.name},#{new_id});"))
        coords = ",".join(_step_real(x) for x in xyz)
        points.append(f"#{new_id}=CARTESIAN_POINT('',({coords}));")
        rows.append({
            "vertex_id": vertex.number, "bit": bit, "original_xyz": vertex.xyz,
            "embedded_xyz": xyz, "original_radius": r, "quantized_radius": target,
            "displacement": math.dist(vertex.xyz, xyz),
        })
    # Insert new entities before the ENDSEC containing the last data entity.
    last_entity = max(e.end for e in document.entities.values())
    section_end = re.match(r"\s*ENDSEC\s*;", _uncomment(document.text[last_entity:]), re.I)
    if section_end is None:
        raise ValueError("Unsupported STEP layout after the final data entity.")
    edits.append((last_entity, last_entity, newline + newline.join(points)))
    for token in _TOKENS.finditer(document.text):
        if _METADATA.fullmatch(token[0]):
            edits.append((token.start(), token.end(), ""))
    output = document.text
    for start, end, replacement in sorted(edits, reverse=True):
        output = output[:start] + replacement + output[end:]
    metadata = {
        "scheme": SCHEME, "delta": delta, "center": center,
        "center_definition": "original vertex mean" if center == document.center() else "explicit fixed center",
        "vertex_ids": [v.number for v in document.vertices],
    }
    marker = re.search(r"END-ISO-10303-21\s*;\s*$", output, re.I)
    comment = "/* QIM_RADIAL_V1 " + json.dumps(metadata, separators=(",", ":"), allow_nan=False) + " */" + newline
    output = output[:marker.start()] + comment + output[marker.start():]
    # Validate serialized coordinates, never recover from saved payload bits.
    recovered = extract(StepDocument(output))
    if recovered["bits"] != "".join(map(str, bits)) or recovered["off_lattice_count"]:
        raise ValueError("STEP serialization lost QIM precision; increase delta or change center.")
    report = {
        **metadata, "bits": "".join(map(str, bits)), "vertex_count": len(bits),
        "max_displacement": max(row["displacement"] for row in rows),
        "input_sha256": hashlib.sha256(document.text.encode("latin-1")).hexdigest(),
        "output_sha256": hashlib.sha256(output.encode("latin-1")).hexdigest(),
        "geometry_warning": WARNING, "vertices": rows,
    }
    return output, report


def _step_real(value: float) -> str:
    result = format(value, ".17g").upper()
    if "." not in result.split("E")[0]:
        result = result.replace("E", ".E") if "E" in result else result + "."
    return result


def extract(document: StepDocument, delta=None, center=None) -> dict:
    metadata = document.metadata()
    if metadata:
        delta = metadata.get("delta") if delta is None else delta
        center = metadata.get("center") if center is None else center
        if metadata.get("vertex_ids") != [v.number for v in document.vertices]:
            raise ValueError("Vertex IDs differ from the embedded metadata; CAD rewriting may have reordered them.")
    if delta is None or center is None:
        raise ValueError("No complete QIM metadata: supply both --delta and --center X Y Z.")
    center = parameters(delta, center)
    rows = []
    for vertex in document.vertices:
        r = radius(vertex.xyz, center)
        index = lattice_index(r, delta)
        error = abs(r / delta - index)
        rows.append({"vertex_id": vertex.number, "bit": index % 2, "radius": r,
                     "lattice_error_in_delta": error, "on_lattice": error <= 1e-6})
    return {
        "scheme": SCHEME, "delta": delta, "center": center,
        "vertex_count": len(rows), "bits": "".join(str(row["bit"]) for row in rows),
        "off_lattice_count": sum(not row["on_lattice"] for row in rows),
        "vertices": rows,
    }


def ensure_new_paths(input_path, paths, overwrite=False):
    source = Path(input_path).resolve()
    outputs = [Path(path).resolve() for path in paths if path is not None]
    if source in outputs or len(set(outputs)) != len(outputs):
        raise ValueError("Input and output files must have distinct paths.")
    for path in outputs:
        if path.exists() and not overwrite:
            raise ValueError(f"Output already exists: {path}. Use --overwrite to replace it.")
        if not path.parent.is_dir():
            raise ValueError(f"Output directory does not exist: {path.parent}")


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

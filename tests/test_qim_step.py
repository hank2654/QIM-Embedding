import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qim_step import StepDocument, choose_bits, embed, extract, quantize, radius


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('label; #123=VERTEX_POINT(''fake'',#1);'), '2;1');
ENDSEC;
DATA;
/* fake entity #999=VERTEX_POINT('',#3); */
#1=CARTESIAN_POINT('a''b',(1.D0, 0., 0.));
#2=CARTESIAN_POINT('',(-1., 0., 0.));
#3=CARTESIAN_POINT('',(0., 2., 0.));
#4=VERTEX_POINT('one',#1);
#5=VERTEX_POINT('two',#2);
#6=VERTEX_POINT('three',#3);
#7=VERTEX_POINT('shared',#1);
#8=AXIS2_PLACEMENT_3D('',#1,$,$);
ENDSEC;
END-ISO-10303-21;
"""


class QimTests(unittest.TestCase):
    def test_parity_lattices_and_nearest_level(self):
        for delta in (0.001, 0.3, 2.0):
            for bit in (0, 1):
                for r in (0.0, 0.1, 1.0, 7.2, 30.0):
                    value = quantize(r, delta, bit)
                    self.assertEqual(round(value / delta) % 2, bit)
                    candidates = [(2 * k + bit) * delta for k in range(math.ceil(r / delta) + 3)]
                    self.assertAlmostEqual(abs(value - r), min(abs(x - r) for x in candidates))
                    self.assertLessEqual(abs(value - r), delta + 1e-12)

    def test_round_trip_and_shared_point_independence(self):
        document = StepDocument(fixture())
        bits = [0, 1, 1, 1]
        text, report = embed(document, 0.1, bits)
        marked = StepDocument(text)
        self.assertEqual(extract(marked)["bits"], "0111")
        self.assertEqual(extract(marked)["off_lattice_count"], 0)
        self.assertEqual(document.entities[1].body, marked.entities[1].body)
        self.assertEqual(document.entities[8].body, marked.entities[8].body)
        self.assertNotEqual(marked.vertices[0].xyz, marked.vertices[3].xyz)
        self.assertEqual(document.center(), tuple(report["center"]))
        self.assertNotEqual(marked.center(), document.center())
        self.assertNotIn("bits", marked.metadata())
        self.assertNotIn("seed", marked.metadata())
        for row in report["vertices"]:
            before = [x - c for x, c in zip(row["original_xyz"], report["center"])]
            after = [x - c for x, c in zip(row["embedded_xyz"], report["center"])]
            for i, j in ((0, 1), (0, 2), (1, 2)):
                self.assertAlmostEqual(before[i] * after[j] - before[j] * after[i], 0)

    def test_all_modes_seeds_and_sparse_overrides(self):
        vertices = StepDocument(fixture()).vertices
        self.assertEqual(choose_bits(vertices, "0"), [0] * 4)
        self.assertEqual(choose_bits(vertices, "1"), [1] * 4)
        self.assertEqual(choose_bits(vertices, seed=42), choose_bits(vertices, seed=42))
        self.assertEqual(choose_bits(vertices, bits="1010"), [1, 0, 1, 0])
        self.assertEqual(choose_bits(vertices, "0", overrides={"#4": 1, "6": 1}), [1, 0, 1, 0])
        self.assertEqual(choose_bits(vertices, "1", seed=42, overrides={"4": "random"})[0], 0)
        for overrides in ({"999": 0}, {"4": 2}, {"4": True}, {"4": 0, "#4": 1}, []):
            with self.assertRaises(ValueError):
                choose_bits(vertices, overrides=overrides)
        for bits in ("1", "000x"):
            with self.assertRaises(ValueError):
                choose_bits(vertices, bits=bits)

    def test_center_vertex_and_crlf(self):
        doc = StepDocument(fixture().replace("\n", "\r\n"))
        text, _ = embed(doc, 0.2, [1] * 4, center=doc.vertices[0].xyz)
        self.assertIn("\r\n", text)
        result = StepDocument(text)
        self.assertAlmostEqual(radius(result.vertices[0].xyz, doc.vertices[0].xyz), 0.2)
        self.assertEqual(extract(result)["bits"], "1111")

    def test_metadata_free_decode_and_reembed(self):
        doc = StepDocument(fixture())
        text, report = embed(doc, 0.02, [1, 0, 1, 0])
        metadata_comment = next(line for line in text.splitlines() if line.startswith("/* QIM_RADIAL_V1"))
        plain = StepDocument(text.replace(metadata_comment, ""))
        self.assertEqual(extract(plain, 0.02, report["center"])["bits"], "1010")
        with self.assertRaises(ValueError):
            extract(plain)
        again, _ = embed(StepDocument(text), 0.03, [0, 1, 0, 1])
        self.assertEqual(again.count("/* QIM_RADIAL_V1"), 1)
        self.assertEqual(extract(StepDocument(again))["bits"], "0101")

    def test_bad_delta_precision_and_layout(self):
        doc = StepDocument(fixture())
        for delta in (0, -1, float("nan"), float("inf"), 1e-30):
            with self.assertRaises(ValueError):
                embed(doc, delta, [0] * 4)
        for center in ([0, 0], [0, float("nan"), 0]):
            with self.assertRaises(ValueError):
                embed(doc, 0.1, [0] * 4, center)
        with self.assertRaises(ValueError):
            StepDocument(fixture().replace("#3=CARTESIAN_POINT", "#1=CARTESIAN_POINT"))
        with self.assertRaises(ValueError):
            StepDocument(fixture().replace("END-ISO-10303-21;", ""))
        with self.assertRaises(ValueError):
            StepDocument(fixture().replace("#8=AXIS2_PLACEMENT_3D('',#1,$,$);", "#8=MAPPED_ITEM('',#1,#2);"))

    def test_metadata_vertex_tampering_and_off_lattice(self):
        text, _ = embed(StepDocument(fixture()), 0.1, [0, 1, 0, 1])
        with self.assertRaises(ValueError):
            extract(StepDocument(text.replace("#4=VERTEX_POINT", "#40=VERTEX_POINT")))
        doc = StepDocument(text)
        result = extract(doc, center=[c + 0.01 for c in doc.metadata()["center"]])
        self.assertGreater(result["off_lattice_count"], 0)

    def test_real_stp_all_modes_and_deltas(self):
        doc = StepDocument.read(ROOT / "examples/2.stp")
        self.assertEqual(len(doc.vertices), 216)
        for mode in ("0", "1", "random"):
            for delta in (0.001, 0.01, 0.1, 1.0):
                with self.subTest(mode=mode, delta=delta):
                    bits = choose_bits(doc.vertices, mode, seed=42)
                    text, report = embed(doc, delta, bits)
                    marked = StepDocument(text)
                    decoded = extract(marked)
                    self.assertEqual(decoded["bits"], "".join(map(str, bits)))
                    self.assertEqual(decoded["off_lattice_count"], 0)
                    self.assertLessEqual(report["max_displacement"], delta + 1e-10)
                    vertex_ids = {v.number for v in doc.vertices}
                    for number, entity in doc.entities.items():
                        if number not in vertex_ids:
                            self.assertEqual(entity.body, marked.entities[number].body)

    def test_committed_example_reports_match_coordinates(self):
        embedded = json.loads((ROOT / "examples/2.embed.json").read_text())
        saved = json.loads((ROOT / "examples/2.extracted.json").read_text())
        decoded = extract(StepDocument.read(ROOT / "examples/2.qim.stp"))
        self.assertEqual(embedded["bits"], decoded["bits"])
        self.assertEqual(saved, json.loads(json.dumps(decoded)))
        self.assertEqual(embedded["vertex_count"], 216)

    def test_cli_files_overwrites_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.stp"
            source.write_text(fixture(), encoding="latin-1")
            marked, embed_report, decoded = (root / name for name in ("marked.stp", "embed.json", "decoded.json"))
            args = [sys.executable, str(ROOT / "embed_step.py"), str(source), str(marked),
                    "--delta", "0.1", "--bits", "0110", "--report", str(embed_report)]
            first = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)
            second = subprocess.run([sys.executable, str(ROOT / "extract_step.py"), str(marked),
                                     "--output", str(decoded)], capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout.strip(), "0110")
            self.assertEqual(json.loads(embed_report.read_text())["bits"], json.loads(decoded.read_text())["bits"])
            self.assertEqual(source.read_text(encoding="latin-1"), fixture())
            bad = subprocess.run(args[:3] + [str(source)] + args[4:] + ["--overwrite"], capture_output=True)
            self.assertEqual(bad.returncode, 2)
            mismatched = subprocess.run([sys.executable, str(ROOT / "extract_step.py"), str(marked),
                                        "--delta", "0.123"], capture_output=True)
            self.assertEqual(mismatched.returncode, 1)


if __name__ == "__main__":
    unittest.main()

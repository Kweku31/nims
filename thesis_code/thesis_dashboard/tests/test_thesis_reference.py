import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_thesis_reference import ROOT, RUN, build, latex_values


class RecordedStudyTests(unittest.TestCase):
    def setUp(self):
        self.reference = json.loads((ROOT / "src/thesis_reference.json").read_text())

    def test_reported_scope_and_slide_values(self):
        data = self.reference
        self.assertEqual((data["packages"], data["comparisons"], data["package_trials"]), (82, 164, 586))
        self.assertEqual((data["direct_trials"], data["archive_trials"], data["archive_pairs"]), (40, 32, 4))
        self.assertAlmostEqual(data["archive_delta"], -10.46, places=2)
        values = latex_values(data)
        self.assertIn(r"\newcommand{\studyAeRSq}{0.907}", values)
        tex = ROOT.parent / "thesis_slides/defence/results.tex"
        if tex.exists():
            self.assertEqual(tex.read_text(), values)

    def test_rebuild_matches_retained_snapshot(self):
        folder = ROOT / "data/jobs/job-c2cbe4fe79e3/output/results" / self.reference["snapshot"]
        if not folder.exists():
            self.skipTest("Archived research reports are optional in the source-only distribution")
        self.assertEqual(build(folder), self.reference)

    def test_rejects_other_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for f in ("run_manifest.json", "transport_studies.json"):
                (folder / f).write_text(json.dumps({"run_id": RUN, "input_sha256": "different"}))
            with self.assertRaisesRegex(ValueError, "matching paired studies"):
                build(folder)

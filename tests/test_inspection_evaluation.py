"""Frozen provenance, abstention accounting and held-out input integrity."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from PIL import Image
from meshlens.inspection_evaluation import evaluate, score_prediction, summarize, verify_frozen_bundle, wilson

ROOT = Path(__file__).resolve().parents[1]


class IndependentEvaluationTests(unittest.TestCase):
    def test_cutoff_ties_and_invalid_scores(self):
        self.assertEqual(score_prediction(1, 1), (1., 'within_range', None))
        self.assertEqual(score_prediction(1.01, 1)[1], 'review')
        self.assertEqual(score_prediction((None, 'unreadable'), 1)[1], 'unusable')
        for score in [None, True, -1, float('inf'), float('nan')]:
            with self.subTest(score=score), self.assertRaises(ValueError):
                score_prediction(score, 1)

    def test_inconclusive_images_are_not_successful_decisions_or_auc_support(self):
        rows = [{'label': 1, 'score': 3, 'decision': 'review', 'wall_ms': 1},
                {'label': 1, 'score': 100, 'decision': 'unusable', 'wall_ms': 1},
                {'label': 0, 'score': 3, 'decision': 'within_range', 'wall_ms': 1},
                {'label': 0, 'score': 0, 'decision': 'unusable', 'wall_ms': 1}]
        m = summarize(rows)
        self.assertEqual(m['defect_recall'], .5)
        self.assertEqual(m['clean_review_or_unusable_rate'], .5)
        self.assertEqual(m['coverage'], .5)
        self.assertEqual(m['scored_images'], 2)
        self.assertEqual(m['scored_images_auroc'], .5)
        self.assertAlmostEqual(wilson(0, 21)[1], .154639018924847, places=12)

    def test_input_tampering_duplicate_paths_and_escape_do_not_reach_scorer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'input.png'
            Image.new('RGB', (32,32), (17,17,17)).save(path)
            row = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'label': 0, 'defect_type': 'good'}
            seen = []
            def scorer(image):
                self.assertIsInstance(image, Image.Image)
                seen.append(image.size)
                return .5
            result = evaluate([row], root, scorer, .5, stress=True)
            self.assertEqual(len(result['records']), 6)
            for bad in [[row,row], [{**row,'sha256':'0'*64}], [{**row,'path':'../outside.png'}]]:
                with self.assertRaises(ValueError):
                    evaluate(bad, root, scorer, .5, stress=False)
            self.assertEqual(len(seen), 6)

    def test_frozen_file_manifest_detects_source_tampering_without_test_images(self):
        frozen = ROOT / 'reports/inspection/frozen_configuration.json'
        if not frozen.is_file():
            self.skipTest('Inspection bundle not packaged')
        content = frozen.read_bytes()
        record = json.loads(content)
        if 'files' not in record:
            self.skipTest('This fixture checks the recovery file-manifest format')
        pin = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / frozen.relative_to(ROOT)
            target.parent.mkdir(parents=True)
            target.write_bytes(content)
            for relative in record['files']:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, path)
            _, _, rows = verify_frozen_bundle(root, target, pin)
            self.assertEqual(len(rows), 78)
            source = root / 'web/texture_detector.js'
            source.write_bytes(source.read_bytes() + b'\n// tampered\n')
            with self.assertRaises(ValueError):
                verify_frozen_bundle(root, target, pin)


if __name__ == '__main__':
    unittest.main()

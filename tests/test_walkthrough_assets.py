"""Educational downloads must remain traceable to the frozen experiment."""
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import unittest
import zipfile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.assets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.ids.append(values['id'])
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])
        if tag == 'img':
            self.assets.append(values)


class WalkthroughAssets(unittest.TestCase):
    def test_download_contains_the_exact_labeled_gallery_and_license(self):
        gallery = json.loads((ROOT / 'artifacts/samples.json').read_text())['samples']
        with zipfile.ZipFile(ROOT / 'web/downloads/MeshLens-18-Benchmark-Examples.zip') as archive:
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['samples'], gallery)
            self.assertEqual(len([name for name in archive.namelist() if name.startswith('images/')]), 18)
            for sample in gallery:
                content = archive.read('images/' + sample['filename'])
                self.assertEqual(hashlib.sha256(content).hexdigest(), sample['sha256'])
                self.assertEqual(content, (ROOT / 'artifacts/samples' / sample['filename']).read_bytes())
            self.assertIn('NOT new independent validation', archive.read('README.md').decode())
            self.assertGreater(len(archive.read('DATASET-LICENSE.txt')), 100)
            self.assertGreater(len(archive.read('DATASET-README.txt')), 100)

    def test_hero_assets_have_model_and_source_provenance(self):
        provenance = json.loads((ROOT / 'web/walkthrough/provenance.json').read_text())
        metadata = json.loads((ROOT / 'artifacts/metadata.json').read_text())
        self.assertEqual(provenance['model_version'], metadata['model_version'])
        self.assertEqual(provenance['model_sha256'], hashlib.sha256((ROOT / 'artifacts/model.onnx').read_bytes()).hexdigest())
        self.assertLess(abs(provenance['observed_score'] - provenance['source_sample']['expected_score']), 3e-8)
        for name, expected in provenance['files'].items():
            content = (ROOT / 'web/walkthrough' / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), expected)
            self.assertEqual(Image.open(io.BytesIO(content)).size, (256, 256))
        self.assertEqual((ROOT / 'web/walkthrough/original.png').read_bytes(), (ROOT / 'artifacts/samples/bent-000.png').read_bytes())

    def test_educational_navigation_has_unique_working_targets_and_alternatives(self):
        parser = PageLinks()
        parser.feed((ROOT / 'web/index.html').read_text())
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for link in parser.links:
            if link.startswith('#'):
                self.assertIn(link[1:], parser.ids)
            elif link.startswith('/') and not link.startswith('/assets/'):
                self.assertTrue((ROOT / 'web' / link[1:]).is_file(), link)
        for image in parser.assets:
            self.assertIn('alt', image)
            self.assertTrue((ROOT / 'web' / image['src'][1:]).is_file())


if __name__ == '__main__':
    unittest.main()

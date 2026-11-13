"""Independent area oracles and exact cross-runtime canonical input bytes."""
import csv
from pathlib import Path
import shutil
import subprocess
import unittest
import numpy as np
from PIL import Image
from meshlens.inspection_input import inspection_rgb8

ROOT = Path(__file__).resolve().parents[1]
NODE = """import{readFileSync}from'node:fs';const[url,w,h,s]=process.argv.slice(1);const{inspectionRgb8}=await import(url);process.stdout.write(inspectionRgb8(new Uint8Array(readFileSync(0)),+w,+h,+s));"""


def pattern(w, h, opaque=False):
    y, x = np.indices((h, w), dtype=np.uint32)
    a = np.empty((h, w, 4), dtype=np.uint8)
    a[..., 0], a[..., 1], a[..., 2] = (11*x+7*y)%256, ((x//3 ^ y//2)*31)%256, ((x+y)*19)%256
    a[..., 3] = 255 if opaque else (17*x+3*y)%256
    return a


class CanonicalInputTests(unittest.TestCase):
    def js(self, data, size):
        if not shutil.which('node'):
            self.skipTest('Node is required')
        h, w, _ = data.shape
        r = subprocess.run(['node', '--input-type=module', '-e', NODE,
                            (ROOT/'web/inspection_input.js').as_uri(), str(w), str(h), str(size)],
                           input=data.tobytes(), capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr.decode(errors='replace'))
        return np.frombuffer(r.stdout, dtype=np.uint8).reshape(size, size, 3)

    def test_independent_two_by_two_oracle(self):
        data = pattern(64, 64, True)
        expected = (data[..., :3].astype(np.uint16).reshape(32, 2, 32, 2, 3).sum(axis=(1, 3))+2)//4
        np.testing.assert_array_equal(inspection_rgb8(Image.fromarray(data), 32), expected.astype(np.uint8))

    def test_alpha_white_composite_preserves_source(self):
        data = pattern(32, 32)
        image = Image.fromarray(data)
        alpha = data[..., 3:4].astype(np.float64)/255
        expected = np.floor(data[..., :3]*alpha + 255*(1-alpha)+.5).astype(np.uint8)
        np.testing.assert_array_equal(inspection_rgb8(image, 32), expected)
        np.testing.assert_array_equal(np.asarray(image), data)

    def test_palette_and_exif_orientation(self):
        image = Image.new('P', (32, 48), 0)
        image.putpalette([0,0,0]*256)
        image.info['transparency'] = 0
        np.testing.assert_array_equal(inspection_rgb8(image, 32), 255)
        source = Image.fromarray(pattern(32, 48, True)[..., :3])
        source.getexif()[274] = 6
        np.testing.assert_array_equal(inspection_rgb8(source, 32), inspection_rgb8(source.transpose(Image.Transpose.ROTATE_270), 32))

    def test_bounds_and_animation(self):
        valid = Image.new('RGB', (32,32))
        for s in [0,7,1025,8.5,True]:
            with self.subTest(size=s), self.assertRaises(ValueError):
                inspection_rgb8(valid, s)
        for dims in [(31,32),(32,4097),(4096,4096)]:
            with self.subTest(dimensions=dims), self.assertRaises(ValueError):
                inspection_rgb8(Image.new('L',dims),32)
        valid.n_frames = 2
        with self.assertRaises(ValueError):
            inspection_rgb8(valid,32)

    def test_fractional_and_extreme_geometry_python_js_exact(self):
        for w,h,s,opaque in [(1024,1024,384,True),(1024,1024,384,False),(1023,769,384,False),
                              (57,103,31,False),(32,33,384,False),(4096,32,17,True),(32,4096,17,False)]:
            with self.subTest(width=w,height=h,size=s,opaque=opaque):
                data=pattern(w,h,opaque)
                np.testing.assert_array_equal(self.js(data,s),inspection_rgb8(Image.fromarray(data),s))

    def test_real_fit_png_input_bytes_match(self):
        with (ROOT/'data/manifest.csv').open(newline='') as f:
            row=next(r for r in csv.DictReader(f) if r['split']=='fit')
        path=ROOT/row['path']
        if not path.is_file():
            self.skipTest('Research dataset unavailable')
        with Image.open(path) as image:
            data = np.asarray(image.convert('RGBA'))
            expected = inspection_rgb8(image, 384)
        np.testing.assert_array_equal(self.js(data,384),expected)


if __name__ == '__main__':
    unittest.main()

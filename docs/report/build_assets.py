#!/usr/bin/env python3
"""Build original, editable SVG documentation figures from the frozen evidence."""
from pathlib import Path
from html import escape
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/assets/diagrams'
INK = '#163f39'
TEAL = '#26766b'
MINT = '#e6eee3'
BG = '#f7f8f2'
MUTED = '#536b62'
LINE = '#c9d7ce'
AMBER = '#a96524'
PALE = '#fff0d9'


class Figure:
    def __init__(self, title, subtitle, height=800):
        self.height = height
        self.items = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}</desc>',
                      '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#26766b"/></marker></defs>',
                      '<rect width="1200" height="100%" fill="#f7f8f2"/>',
                      '<style>text{font-family:Arial,Helvetica,sans-serif} .small{font-size:18px} .body{font-size:22px} .label{font-size:24px;font-weight:700}</style>']
        self.text(38, 41, 'MESHLENS  /  PROJECT DOCUMENTATION', 17, MUTED, weight=700)
        self.text(38, 96, title, 36, INK, weight=700)
        self.text(38, 130, subtitle, 20, MUTED)

    def text(self, x, y, value, size=22, color=INK, weight=400, anchor='start'):
        self.items.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>')

    def rect(self, x, y, w, h, fill='white', stroke=LINE, radius=16, dash=False):
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"'+(' stroke-dasharray="8 7"' if dash else '')+'/>')

    def box(self, x, y, w, h, title, lines=(), fill='white', title_size=25):
        self.rect(x, y, w, h, fill)
        self.text(x+22, y+38, title, title_size, INK, 700)
        for i, line in enumerate(lines):
            self.text(x+22, y+72+i*28, line, 21, MUTED)

    def arrow(self, points, label='', lx=None, ly=None, dashed=False):
        coords = ' '.join(f'{x},{y}' for x, y in points)
        self.items.append(f'<polyline points="{coords}" fill="none" stroke="{TEAL}" stroke-width="2.5" marker-end="url(#arrow)"'+(' stroke-dasharray="7 6"' if dashed else '')+'/>')
        if label:
            self.text(lx, ly, label, 18, MUTED)

    def save(self, name, note='Source release 5f11b39  |  Kumar Waibhav Akshat  |  14 November 2026'):
        self.text(38, self.height-25, note, 17, MUTED)
        self.items.append('</svg>')
        (OUT / (name+'.svg')).write_text('\n'.join(self.items)+'\n', encoding='utf-8')


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    evaluation = json.loads((ROOT/'reports/inspection/evaluation.json').read_text())
    # Brand artwork is original documentation artwork, not an inference result.
    b = Figure('Mesh inspection with evidence', 'A reproducible browser application and an honest engineering case study', 430)
    b.rect(38, 170, 720, 180, INK, INK)
    b.text(66, 224, 'MeshLens', 48, '#ffffff', 700)
    b.text(66, 268, 'Local inference. Visible limits. Reproducible results.', 24, '#dce8db')
    b.text(66, 310, 'Technical report  /  Architecture  /  Development lessons', 20, '#dce8db')
    for row in range(5):
        for col in range(7):
            x, y = 830+col*43, 193+row*31
            b.items.append(f'<path d="M{x} {y}l21 -14l21 14l-21 14Z" fill="none" stroke="#699488" stroke-width="2"/>')
    b.items.append('<circle cx="1000" cy="250" r="43" fill="none" stroke="#a96524" stroke-width="5"/><path d="M1032 281l48 48" stroke="#a96524" stroke-width="10" stroke-linecap="round"/>')
    b.save('brand-banner', 'Kumar Waibhav Akshat  |  Research and human review prototype  |  Code MIT / benchmark CC BY-NC-SA 4.0')

    f = Figure('System architecture', 'Offline development, verified static delivery, and inference on the visitor device', 900)
    f.rect(28, 170, 1144, 215, MINT, LINE)
    f.text(50, 204, 'OFFLINE DEVELOPMENT', 18, MUTED, 700)
    f.box(50, 228, 330, 132, 'Licensed Grid data', ['160 fit / 52 tune / 52 calibrate', '78 official test images'])
    f.box(435, 228, 330, 132, 'Python workflows', ['Fit, select, calibrate, freeze', 'Evaluate and verify evidence'])
    f.box(820, 228, 330, 132, 'Frozen release bundle', ['Detector + calibration + hashes', 'AE checkpoint and ONNX'])
    f.arrow([(380, 291), (435, 291)])
    f.arrow([(765, 291), (820, 291)])
    f.box(435, 425, 330, 114, 'Node build and Vercel', ['Verified HTML / JS / model assets'])
    f.arrow([(985, 360), (985, 407), (600, 407), (600, 425)])
    f.rect(28, 582, 1144, 243, 'white', TEAL)
    f.text(50, 617, 'BROWSER BOUNDARY  /  INSPECTION PIXELS REMAIN LOCAL', 18, MUTED, 700)
    f.box(50, 650, 330, 126, 'Input and suitability', ['Still image or camera frame', 'Bounds, orientation, RGB resize'], BG)
    f.box(435, 650, 330, 126, 'Local model execution', ['Texture worker: active decision', 'ONNX AE: separate evidence'], MINT)
    f.box(820, 650, 330, 126, 'Explain and record', ['Review / range / input review', 'Local history and JSON / CSV'], BG)
    f.arrow([(600, 539), (600, 650)], 'asset download', 620, 567)
    f.arrow([(380, 715), (435, 715)])
    f.arrow([(765, 715), (820, 715)])
    f.text(50, 804, 'No Python inference API  |  No image upload for scoring  |  Browser-local history is not a shared audit store', 18, MUTED)
    f.save('system-architecture')

    f = Figure('Data and evaluation workflow', 'Partition by source image before patches, alterations, model selection or calibration', 815)
    f.box(40, 175, 1120, 94, 'MVTec AD Grid', ['342 original images  |  264 normal training images  |  78 official test images  |  57 masks'])
    xs = [40, 325, 610, 895]
    roles = [('Fit', ['160 normal', 'Fit normal statistics']), ('Tune', ['52 normal / 260 altered', 'Candidate selection']), ('Calibration', ['52 separate normal', 'Score rank 51']), ('Official test', ['21 normal / 57 defects', 'Frozen evaluation'])]
    for x, (title, lines) in zip(xs, roles):
        f.arrow([(x+132, 269), (x+132, 320)])
        f.box(x, 320, 265, 145, title, lines, PALE if title=='Official test' else 'white', 25)
    f.box(40, 530, 835, 125, 'Freeze before evaluation', ['Selected method + score rule + normal-only calibration threshold', 'Model, implementation, source manifest and protocol are hash-pinned'], MINT)
    for x in xs[:3]:
        f.arrow([(x+132, 465), (x+132, 530)])
    f.box(895, 530, 265, 125, 'Measure outcomes', ['Misses, alerts, coverage', 'Six replay conditions'], PALE, 24)
    f.arrow([(1027, 465), (1027, 530)])
    f.arrow([(875, 593), (895, 593)])
    f.text(40, 707, 'Derived data stay with their source role. Test images and masks do not fit the detector or set its threshold.', 21, MUTED)
    f.text(40, 743, 'The recovered release repeats a known benchmark. Independent target-line qualification remains outstanding.', 21, AMBER)
    f.save('data-workflow')

    f = Figure('Two models with separate responsibilities', 'The active texture detector sets the review decision; the autoencoder supplies comparison views', 1040)
    f.box(320, 172, 560, 88, 'One native input image', ['Resolve orientation and composite transparency'])
    f.arrow([(465, 260), (465, 285), (305, 285), (305, 310)])
    f.arrow([(735, 260), (735, 285), (895, 285), (895, 310)])
    left = [('Canonical area RGB input', ['256 x 256 RGB, area-rgb8-v1']), ('Find repeat directions', ['Contrast normalization + autocorrelation']), ('Compare neighboring repetitions', ['Local 7 x 7 and cell 19 x 19 windows']), ('Combine, normalize and score', ['0.6 local + 0.4 cell; normal-fit scale', 'Mean largest 328 responses; round to 8 dp']), ('Active output', ['Review if score > 1.01049636', 'Relative detector map; explicit inconclusive'])]
    right = [('Separate reconstruction input', ['256 x 256 RGB float32 AE view']), ('Convolutional encoder', ['12 / 16 / 24 / 8 channels']), ('Decoder and image reconstruction', ['25,339 learned parameters; ONNX Web']), ('Reconstruction residual', ['Per-pixel mean squared RGB error', 'Historical score averages largest 1%']), ('Historical evidence only', ['Reconstruction and AE error map', 'Does not set the active review decision'])]
    for i, ((a, al), (b, bl)) in enumerate(zip(left, right)):
        y = 310+i*130
        f.box(40, y, 530, 112, a, al, MINT if i==4 else 'white', 24)
        f.box(630, y, 530, 112, b, bl, BG if i==4 else 'white', 24)
        if i<4:
            f.arrow([(305, y+112), (305, y+130)])
            f.arrow([(895, y+112), (895, y+130)])
    f.text(40, 985, 'Both paths execute locally. Uploading an image does not train or update either model.', 21, MUTED)
    f.save('model-architecture')

    f = Figure('Historical autoencoder architecture', 'Full-frame inference shapes are shown; the original model was trained on 64 x 64 normal patches', 650)
    stages=[('Input', ['3 x 256 x 256']), ('Reflect padding', ['16 px each side', '3 x 288 x 288']), ('Linear bottleneck', ['8 x 36 x 36']), ('Reconstruction', ['Crop 16 px each side', '3 x 256 x 256'])]
    for x,(title,lines) in zip([40,330,620,910],stages):
        f.box(x,185,250,140,title,lines, MINT if title=='Linear bottleneck' else 'white',24)
        if x<910:f.arrow([(x+250,255),(x+290,255)])
    f.box(40,375,540,165,'Encoder', ['Conv 3->12, k3 s1; LeakyReLU(0.1)', 'Conv 12->16->24->8, each k4 s2', 'Spatial sizes: 288 -> 144 -> 72 -> 36'], 'white')
    f.box(620,375,540,165,'Decoder', ['Transpose conv 8->24->16->12, k4 s2', 'Conv 12->3, k3 s1; sigmoid output', 'Spatial sizes: 36 -> 72 -> 144 -> 288'], 'white')
    f.text(40,590,'25,339 parameters  |  26 recorded epochs  |  training seed 43  |  frozen historical threshold 0.02402208',21,MUTED)
    f.save('autoencoder-architecture')

    f = Figure('Inspection interaction sequence', 'The active worker path returns evidence before a completed record is stored', 820)
    actors=[(145,'User'),(455,'Main browser UI'),(765,'Texture worker'),(1065,'Local history')]
    for x,title in actors:
        f.rect(x-115,175,230,64,MINT)
        f.text(x,216,title,23,INK,700,'middle')
        f.items.append(f'<path d="M{x} 239V722" stroke="{LINE}" stroke-width="2" stroke-dasharray="7 7"/>')
    f.arrow([(145,288),(455,288)],'choose image',210,276)
    f.text(470,334,'Decode and validate input',20,MUTED)
    f.arrow([(455,380),(765,380)],'canonical RGB + request ID',487,367)
    f.text(780,427,'Score or return inconclusive',20,MUTED)
    f.arrow([(765,477),(455,477)],'score + map / reason',493,464)
    f.arrow([(455,545),(145,545)],'show decision and evidence',185,532)
    f.arrow([(455,614),(1065,614)],'store completed record with model / threshold provenance',479,601)
    f.text(50,698,'Separate ONNX AE reconstruction supplies its own evidence tabs. It does not replace an unavailable detector.',20,MUTED)
    f.text(50,742,'Cancellation, stale responses and model failures do not become a new successful history record.',20,AMBER)
    f.save('inference-sequence')

    f = Figure('Deployment and verification architecture', 'Hosting and software verification are separate status paths for the same source commit', 850)
    f.box(405,175,390,100,'GitHub source commit', ['Code, frozen artifacts, evidence and docs'],MINT)
    f.arrow([(505,275),(505,310),(300,310),(300,350)])
    f.arrow([(695,275),(695,310),(900,310),(900,350)])
    f.box(40,350,520,178,'GitHub Actions source job', ['Frozen Python / Node dependencies', 'Python + browser tests, lint, runtime parity', 'Verified release build'], 'white')
    f.box(640,350,520,178,'Vercel static deployment', ['npm ci -> npm run build -> dist/', 'Serve UI, JavaScript, ONNX / WASM assets', 'No Python server and no scoring API'], 'white')
    f.arrow([(300,528),(300,585)],'requires source job success',320,562)
    f.arrow([(900,528),(900,585)])
    f.box(40,585,520,135,'Full dataset audit job', ['Verify pinned acquisition and every image / mask', 'Python tests + WASM checks on all 78 test images'],MINT,24)
    f.box(640,585,520,135,'Visitor browser', ['Download verified assets and execute locally', 'Inspect model readiness and real user journey'],MINT)
    f.text(40,777,'A green deployment alone does not establish green CI, field accuracy or acceptable operational false alarms.',21,AMBER)
    f.save('deployment-architecture')

    m = evaluation['model']
    f = Figure('Benchmark results at the frozen threshold', '78 known Grid test images; image-level outcomes from the recovered release', 730)
    f.text(220,206,'Review',23,INK,700,'middle');f.text(460,206,'Within range',23,INK,700,'middle')
    f.text(35,285,'Defective',22,INK,700);f.text(35,455,'Normal',22,INK,700)
    for x,y,count,sub,fill in [(135,230,m['true_positive'],'Defects flagged',MINT),(375,230,m['false_negative'],'Missed defect',PALE),(135,400,m['false_positive'],'False alarms',PALE),(375,400,m['true_negative'],'Correct normal',MINT)]:
        f.rect(x,y,220,150,fill);f.text(x+110,y+76,count,50,INK,700,'middle');f.text(x+110,y+120,sub,20,MUTED,400,'middle')
    f.box(680,230,480,320,'Read both kinds of error', [f'Recall: {m["true_positive"]}/57 = {100*m["recall"]:.2f}%', 'False alarms: 4/21 = 19.05%', f'Precision: {100*m["precision"]:.2f}%', f'AUROC: {m["auroc"]:.4f}', 'Coverage: 78/78 scored; 0 inconclusive', 'Declared false-alarm limit: 5%'], 'white')
    f.text(40,610,'Historical reconstruction AE: 11/57 defects flagged, 46 missed and 0/21 normal false alarms.',21,MUTED)
    f.text(40,653,'The 5% false-alarm goal was not met. These counts do not establish independent factory performance.',21,AMBER)
    f.save('benchmark-results')

    f = Figure('Capture stress exposes the operating limits', 'Deterministic transformations of the same 78 benchmark images; the threshold stays fixed', 800)
    labels={'original':'Original','brightness_070':'Brightness x0.70','brightness_130':'Brightness x1.30','shift_8x4_ref256':'Reflected shift 8 / 4 px','blur_sigma_0p8_ref256':'Blur sigma 0.8','jpeg_quality_75':'JPEG quality 75'}
    f.text(40,194,'CONDITION',17,MUTED,700);f.text(355,194,'NORMAL FALSE ALARMS  /  OUT OF 21',17,MUTED,700);f.text(1040,194,'DEFECTS',17,MUTED,700)
    for i,(key,label) in enumerate(labels.items()):
        row=evaluation['conditions'][key];y=245+i*67;rate=row['false_alarm_rate']
        f.text(40,y+17,label,22,INK)
        f.rect(355,y-8,555,33,MINT, MINT,6)
        if rate:f.rect(355,y-8,555*rate,33,'#bd813c','#bd813c',6)
        f.text(935,y+17,f'{row["false_alarms"]}/21',22,INK,700)
        f.text(1085,y+17,f'{row["model"]["true_positive"]}/57',22,INK,700,'middle')
    f.text(40,692,'A shift flagged every normal image. High recall alone can hide an unusable review workload.',23,AMBER,700)
    f.text(40,737,'No inconclusive inputs were recorded in these six conditions. Simulated stress is not a physical camera study.',20,MUTED)
    f.save('stress-results')

    f = Figure('Release history and the CI repair', 'Published source commits and their workflow outcomes', 855)
    timeline=[('31 Oct','16e8150','Initial autoencoder and application','First source check failed',False),('31 Oct','2bc8231','Frozen CSV integrity and verification','Source and data checks passed',True),('09 Nov','55d3593','Guided interface and dataset explanation','Source and data checks passed',True),('13 Nov','acafd50','Specialized detector and verified workflow','Source and data checks passed',True),('13 Nov','2d33d61','Cross-platform text normalization','Cleanup-test race caused CI failure',False),('13 Nov','5f11b39','Fix process reaping race in timeout test','Source and full dataset audit passed',True)]
    f.items.append(f'<path d="M65 193V727" stroke="{LINE}" stroke-width="4"/>')
    for i,(date,sha,title,detail,success) in enumerate(timeline):
        y=207+i*87;color=TEAL if success else AMBER
        f.items.append(f'<circle cx="65" cy="{y}" r="9" fill="{color}"/>')
        f.text(94,y-2,f'{date} 2026  /  {sha}',18,MUTED,700)
        f.text(330,y-2,title,23,INK,700)
        f.text(330,y+30,detail,20,color)
    f.text(40,785,'Old failed runs remain in history. A passing later run verifies that commit, not every possible device or use case.',20,MUTED)
    f.save('release-timeline')

    f = Figure('Responsive behavior specified in CSS', 'Layout schematic only; this is not a mobile screenshot or a physical-device certification', 755)
    f.rect(40,185,650,370,'white',LINE,18);f.rect(62,210,606,42,MINT);f.rect(62,274,180,245,BG);f.rect(260,274,408,245,MINT)
    f.text(75,237,'Desktop navigation',20,MUTED);f.text(80,313,'Source controls',20,MUTED);f.text(284,313,'Evidence and result',22,INK,700)
    f.rect(800,185,310,370,'white',LINE,25);f.rect(818,208,274,45,MINT);f.rect(818,270,274,84,BG);f.rect(818,372,274,150,MINT)
    f.text(835,238,'Wrapped navigation',19,MUTED);f.text(835,318,'Source controls',20,MUTED);f.text(835,415,'Evidence',22,INK,700);f.text(835,450,'and result',22,INK,700)
    f.text(40,598,'1100 px: tighter spacing and toolbars. 820 px: main grids stack. 600 px: compact navigation and controls.',20,MUTED)
    f.text(40,639,'Reduced motion, reduced transparency, dark appearance and forced-colors rules are present.',20,MUTED)
    f.text(40,687,'Current delivery includes fresh desktop captures. Physical phones, screen readers and camera hardware remain to test.',20,AMBER)
    f.save('responsive-layout')
    print(f'Built {len(list(OUT.glob("*.svg")))} editable SVG figures in {OUT}')


if __name__ == '__main__':
    build()

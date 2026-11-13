# Deployment and local operation

MeshLens runs the inspection detector and the separate reconstruction autoencoder on the
visitor's device. The static host serves versioned model files, metadata, JavaScript and
WebAssembly assets. It needs Node.js to build the app and no Python inference server.

## Local web app

From the project root:

```bash
npm ci
npm test
npm run build
npm run serve
```

Open the printed URL, normally `http://127.0.0.1:4173`. The Node server binds to loopback.
On Windows use `npm.cmd` for these commands if PowerShell blocks the `npm.ps1` shim.

If port 4173 is occupied, let the operating system choose an available port:

```bash
node --input-type=module -e "import {startServer} from './scripts/serve_web.mjs'; const server = await startServer({port:0}); console.log('http://127.0.0.1:' + server.address().port)"
```

Open the URL that this command prints. Keep the terminal running, and press `Ctrl+C` to stop
your server. Serve `dist/` through HTTP. Opening `index.html` with `file://` can block model
and WebAssembly fetches.

The build verifies and copies the shipped release. It does not download the training data,
fit a new detector or train the autoencoder. The detector's score, threshold and heatmap belong
to its own release. The autoencoder's reconstruction and residual provide separate visual
evidence. Check [the model card](MODEL_CARD.md) for the exact decision method and measured results.

## Vercel

Use the existing `kumarwaibhav/MeshLens` repository integration. These settings are recorded
in `vercel.json`:

| Setting | Value |
|---|---|
| Root directory | Repository root |
| Framework | Other |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | `dist` |

Push the reviewed source through the [Windows GitHub steps](github-windows.md), then inspect
the connected deployment. Confirm the deployed model version against the delivered detector
metadata. A green build or GitHub push alone does not establish that the new release is live.

## Other static hosts

Cloudflare Pages can build with `npm ci && npm run build` and output `dist`, or receive a
locally built release. Preserve correct asset paths, content types and HTTPS serving.

For GitHub Pages, use a root user site or a tested custom domain. Repository subpath hosting
requires a tested base-path configuration. Root-relative model/runtime asset URLs cannot be
assumed to work under a project subdirectory.

The registered ChatGPT preview is owner-private. Updating it preserves that audience.
A private preview and the public Vercel deployment are separate destinations with separate
versions and sharing settings.

## Deployment smoke checks

Run these checks on the deployed HTTPS origin, including a fresh browser session:

- Wait for the detector and reconstruction model to become ready. Check the displayed version
  and threshold against the frozen metadata.
- Run each guided example. Read its known label, actual decision and explanation. Benchmark
  examples demonstrate behavior; they are not newly collected validation data.
- Compare Original, Detector map, Reconstruction and AE error map. The detector map is a
  relative response. The AE views illustrate reconstruction and do not set the active score.
- Upload a supported still image. Check oversized, corrupt and unsupported files, as well as
  a photo that cannot establish a usable mesh pattern. These cases must show an explanation.
  An input below the detector's minimum side length, beyond its aspect-ratio limit or without
  usable repetition must request input review without a numeric defect decision.
- Check that a missing, corrupted or failed detector asset blocks decisions. An older
  autoencoder score must not silently become the active detector result.
- Test retry after a failed load, sequential replay, history clear/recovery and CSV/JSON downloads.
  Confirm exported results retain the model version and threshold used for each inspection.
- Test keyboard navigation and visible focus. Inspect narrow mobile widths, landscape,
  enlarged text and zoom without horizontal clipping or inaccessible controls.
- Start camera sampling only through its control. Check permission denial and stop/restart.
  Verify a still-image alternative remains usable.

Camera capture needs HTTPS or localhost and browser permission. CPU/memory, decode time and
model load time vary across devices. Camera mode samples serially and does not establish
full-video-FPS performance. Browser-local history is device-specific and can be cleared.
Physical camera hardware, line timing and long-duration operation need target-system checks.

Run a clean build immediately before deployment. `scripts/prepare_ui_review.mjs` prepares a
local review fixture. Never deploy its modified output. `npm run build` recreates the verified
release from source.

Use the [workflow guide](RUNBOOK.md) for exact Python/data workflows and the
[field validation guide](FIELD_VALIDATION.md) before making operational accuracy claims.
The [design handoff](design/DESIGN_HANDOFF.md) and
[accessibility review](design/ACCESSIBILITY_REVIEW.md) record the earlier UI revision and its
verification scope; repeat relevant checks after changing the interface.

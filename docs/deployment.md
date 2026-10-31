# Deployment and local operation

The actual trained ONNX model runs in the browser. Python is used for development and offline
analysis; no Python inference process is required on the web host.

## Local web app

```bash
npm ci
npm run build
npm run serve
```

The Node-native server binds to loopback on port 4173 by default. No Python installation is
needed for this local application path. Any compatible static HTTP server can serve `dist/`.

Open http://127.0.0.1:4173. Wait for model ready, inspect a bundled sample and check the score,
threshold, reconstruction and residual evidence. Serve through HTTP rather than opening a
`file://` page, because local model/WebAssembly fetches can otherwise fail.

## Vercel static deployment

Import the extracted source repository. Use Framework Other, Install Command `npm ci`, Build
Command `npm run build`, Output Directory `dist` and the repository root. The Node-native static build requires no Python on the hosting service. It does not download
raw data or retrain.
Deploy and verify real inference, not only the host's successful-build status.

## Cloudflare Pages

Use `npm ci && npm run build` and output `dist` on a Node.js build image, or publish
a locally built static output using supported direct upload. Check model/WASM asset paths
and correct MIME serving on the chosen HTTPS domain.

## GitHub Pages

A root user-site/custom domain is the straightforward configuration for root-relative asset
URLs. Repository subpath hosting needs a tested base-path adaptation; do not assume existing
root-relative model URLs work under an arbitrary subdirectory.

## Live preview audience

The registered MeshLens preview is owner-private by default. Publication status and the final
working URL are verified separately. A deployed private preview is not automatically a public
portfolio link; use sharing controls deliberately for the intended audience.

## Deployment smoke checks

- Model loading completes and a real sample produces finite inference results.
- Model version and threshold match the frozen metadata.
- Input/reconstruction/residual views work and history updates.
- CSV export and Clear work; replay starts and stops without overlapping inference.
- Narrow-screen controls remain readable and keyboard accessible.
- Camera sampling starts only on user request and requires browser permission.

Browser memory/CPU and load times vary. Camera operation needs HTTPS or localhost and browser
permission. Local history can be cleared and does not synchronize across devices. Physical
camera operation and production throughput require their own verification.

See the [workflow guide](RUNBOOK.md) for exact environment setup, Windows commands,
fresh-versus-reused training, input bounds, camera cadence and latency definitions. Camera
software/mock-stream checks do not verify physical camera hardware or production line timing.

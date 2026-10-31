/** Loopback static server for the finished browser app. No Python required. */
import http from 'node:http';
import { realpath, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dist');
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.wasm': 'application/wasm', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.pdf': 'application/pdf', '.md': 'text/plain; charset=utf-8' };
const within = (root, candidate) => candidate === root || (!path.relative(root, candidate).startsWith('..') && !path.isAbsolute(path.relative(root, candidate)));
export async function startServer({ root = ROOT, port = 4173, host = '127.0.0.1' } = {}) {
  const canonical = await realpath(root);
  if (!(await stat(canonical)).isDirectory()) throw new Error('Build the application before starting the server.');
  const server = http.createServer(async (request, response) => {
    const send = (code, message) => { response.writeHead(code, { 'Content-Type': 'text/plain; charset=utf-8' }); response.end(request.method === 'HEAD' ? undefined : message); };
    response.setHeader('X-Content-Type-Options', 'nosniff'); response.setHeader('Referrer-Policy', 'same-origin'); response.setHeader('Permissions-Policy', 'camera=(self), microphone=(), geolocation=()'); response.setHeader('Cache-Control', 'no-cache');
    if (!['GET', 'HEAD'].includes(request.method)) { response.setHeader('Allow', 'GET, HEAD'); send(405, 'Method not allowed.'); return; }
    try {
      if (!request.url || request.url.length > 4096) { send(400, 'Invalid request path.'); return; }
      let decoded; try { decoded = decodeURIComponent(request.url.split('?')[0]); } catch { send(400, 'Invalid request path.'); return; }
      if (!decoded.startsWith('/') || /[\\\0]/.test(decoded) || decoded.split('/').some((segment) => segment.startsWith('.'))) { send(403, 'Path not allowed.'); return; }
      let candidate = path.resolve(canonical, `.${decoded}`);
      if (!within(canonical, candidate)) { send(403, 'Path not allowed.'); return; }
      candidate = await realpath(candidate); if (!within(canonical, candidate)) { send(403, 'Path not allowed.'); return; }
      let info = await stat(candidate);
      if (info.isDirectory()) { candidate = await realpath(path.join(candidate, 'index.html')); if (!within(canonical, candidate)) { send(403, 'Path not allowed.'); return; } info = await stat(candidate); }
      if (!info.isFile()) { send(404, 'File not found.'); return; }
      response.writeHead(200, { 'Content-Type': MIME[path.extname(candidate).toLowerCase()] || 'application/octet-stream', 'Content-Length': info.size });
      if (request.method === 'HEAD') { response.end(); return; }
      const stream = createReadStream(candidate); stream.on('error', () => response.destroy()); response.on('close', () => stream.destroy()); stream.pipe(response);
    } catch (error) { const missing = ['ENOENT', 'ENOTDIR'].includes(error.code); send(missing ? 404 : 500, missing ? 'File not found.' : 'Could not serve the requested file.'); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, host, () => { server.removeListener('error', reject); resolve(); }); });
  return server;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { const server = await startServer(); console.log(`MeshLens running at http://127.0.0.1:${server.address().port}/`); }
  catch (error) { console.error(`Server could not start: ${error.code === 'EADDRINUSE' ? 'Port 4173 is already in use.' : error.message}`); process.exitCode = 1; }
}

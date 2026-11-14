import sharp from 'sharp';
import { readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../assets/diagrams/', import.meta.url));
for (const name of (await readdir(root)).filter((item) => item.endsWith('.svg'))) {
  await sharp(path.join(root, name), { density: 192 }).png().toFile(path.join(root, name.replace(/\.svg$/, '.png')));
}
console.log('Rendered all documentation diagrams as PNG. SVG originals remain editable.');

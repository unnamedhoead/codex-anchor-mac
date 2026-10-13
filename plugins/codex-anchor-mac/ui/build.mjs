// One self-contained HTML file: the host serves it as a resource, so it
// cannot fetch a sibling script or stylesheet.
import { build } from 'esbuild';
import { readFile, writeFile, mkdir } from 'node:fs/promises';

const result = await build({
  entryPoints: ['src/app.ts'],
  bundle: true, format: 'iife', minify: true, write: false,
  target: ['safari17'],
});
const js = result.outputFiles[0].text;
const shell = await readFile('src/panel.html', 'utf8');
await mkdir('dist', { recursive: true });
await writeFile('dist/panel.html', shell.replace('/*BUNDLE*/', () => js), 'utf8');
console.log(`dist/panel.html written, ${js.length} bytes of JS`);

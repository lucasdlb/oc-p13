#!/usr/bin/env node
/**
 * Capture automatique de l'UI pour review visuelle agentique.
 *
 * Usage:
 *   npm run capture -- [label]
 *   CAPTURE_BASE_URL=http://localhost:4200 npm run capture -- dashboard-v3
 *
 * Preconditions:
 *   - Le serveur Angular doit tourner sur CAPTURE_BASE_URL.
 *
 * Sortie:
 *   .scratch/ui-reviews/<label>/<viewport>-<state>.png
 *   .scratch/ui-reviews/<label>/notes.md
 */
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

if (process.argv.includes('--help') || process.argv.includes('-h')) {
  console.log(`Usage: npm run capture -- [label]

Environment:
  CAPTURE_BASE_URL  Running app URL. Defaults to http://localhost:4200.

Output:
  .scratch/ui-reviews/<label>/`);
  process.exit(0);
}

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..', '..');
const baseUrl = process.env.CAPTURE_BASE_URL ?? 'http://localhost:4200';
const label = process.argv[2] ?? new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
const outDir = resolve(repoRoot, '.scratch', 'ui-reviews', label);

const viewports = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'laptop', width: 1280, height: 800 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
];

const states = [
  {
    name: 'initial',
    prepare: async (page) => {
      await page.waitForSelector('cg-board', { timeout: 15000 });
    },
  },
  {
    name: 'after-demo-move',
    prepare: async (page) => {
      const demoButton = page.getByRole('button', { name: /Demo/i });
      if (await demoButton.count()) {
        await demoButton.click();
        // Laisse le temps a l'appel backend / analyse de se stabiliser.
        await page.waitForTimeout(4000);
      }
    },
  },
];

await mkdir(outDir, { recursive: true });

const browser = await chromium.launch();
const captured = [];

for (const viewport of viewports) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  for (const state of states) {
    await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 30000 });
    await state.prepare(page);
    const file = resolve(outDir, `${viewport.name}-${state.name}.png`);
    await page.screenshot({ path: file, fullPage: true });
    captured.push(`${viewport.name}-${state.name}.png`);
    console.log(`captured ${file}`);
  }

  await context.close();
}

await browser.close();

const notes = `# Review UI — ${label}

- Date: ${new Date().toISOString()}
- Base URL: ${baseUrl}
- Captures: ${captured.join(', ')}

## Observations

- (a remplir par l'agent de review)

## Directions proposees

1.
2.
3.

## Decision

- (direction retenue et rationale)
`;

await writeFile(resolve(outDir, 'notes.md'), notes, 'utf8');
console.log(`\nOK: ${captured.length} captures dans ${outDir}`);

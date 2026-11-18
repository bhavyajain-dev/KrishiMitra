/**
 * Generates a static index.html shell for Render Free Static Site deployment.
 * Renders every route's own HTML using the compiled TanStack Start / Nitro server entry.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const serverEntryPath = path.resolve(__dirname, '../.output/server/index.mjs');
const publicDir = path.resolve(__dirname, '../.output/public');
const targetIndexPath = path.join(publicDir, 'index.html');

const ROUTE_SHELLS = [
  'dashboard/index.html',
  'auth/index.html',
  'weather/index.html',
  'crop-plan/index.html',
  'farms/index.html',
  'market/index.html',
  'alerts/index.html',
  'expenses/index.html',
  'profile/index.html',
  'ai-mitra/index.html',
  'ai-saathi/index.html',
  'recommendations/index.html',
  '200.html',
];

async function renderPath(handler, urlPath, hops = 0) {
  const response = await handler.fetch(new Request(`http://localhost${urlPath}`), {}, { waitUntil: () => {} });
  // Old addresses (e.g. /ai-saathi) redirect: store the page they lead to.
  const location = response.headers.get('location');
  if (response.status >= 300 && response.status < 400 && location && hops < 3) {
    return renderPath(handler, new URL(location, 'http://localhost').pathname, hops + 1);
  }
  if (response.status !== 200) {
    throw new Error(`Rendering ${urlPath} returned HTTP ${response.status}`);
  }
  return response.text();
}

async function generateStaticShell() {
  if (!fs.existsSync(serverEntryPath)) {
    console.error(`[StaticShell] Error: Server entry not found at ${serverEntryPath}`);
    process.exit(1);
  }

  const serverModule = await import(`file://${serverEntryPath}`);
  const handler = serverModule.default;

  console.log('[StaticShell] Rendering static HTML from compiled server entry...');
  const homeHtml = await renderPath(handler, '/');
  fs.writeFileSync(targetIndexPath, homeHtml, 'utf-8');
  console.log(`[StaticShell] Created ${targetIndexPath} (${homeHtml.length} bytes)`);

  // Each route gets its OWN rendered HTML. (Copying the home page to every
  // route made React's first render disagree with the HTML on every page,
  // logging hydration error #418 in the browser console.)
  for (const relPath of ROUTE_SHELLS) {
    const urlPath = relPath === '200.html' ? '/' : `/${relPath.replace(/\/index\.html$/, '')}`;
    const html = urlPath === '/' ? homeHtml : await renderPath(handler, urlPath);
    const destPath = path.join(publicDir, relPath);
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    fs.writeFileSync(destPath, html, 'utf-8');
    console.log(`[StaticShell] ${urlPath} -> ${relPath} (${html.length} bytes)`);
  }
}

generateStaticShell().catch((err) => {
  console.error('[StaticShell] Error generating static shell:', err);
  process.exit(1);
});


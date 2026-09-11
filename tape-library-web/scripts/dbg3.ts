import { chromium } from '@playwright/test';
const b = await chromium.launch();
const page = await b.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 200)));
await page.goto('http://localhost:5173/libraries', { waitUntil: 'domcontentloaded' });
for (const t of [3, 8, 15]) {
  await page.waitForTimeout(t === 3 ? 3000 : (t - [3,8,15][[3,8,15].indexOf(t)-1]) * 1000);
  const has = await page.getByText('03584L32').first().isVisible().catch(() => false);
  console.log(`t=${t}s 03584L32 visible:`, has);
  if (has) break;
}
await b.close();

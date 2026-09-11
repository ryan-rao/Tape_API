import { chromium } from '@playwright/test';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 200)));
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 200)); });
page.on('requestfailed', (r) => console.log('REQFAIL:', r.url().slice(0, 100)));
const t0 = Date.now();
await page.goto('http://172.16.12.186:8080/libraries', { waitUntil: 'domcontentloaded' });
// 记录每个 API 请求完成时间
page.on('requestfinished', (r) => { if (r.url().includes('/api/')) console.log(`+${Date.now() - t0}ms done:`, r.url().slice(0, 80)); });
for (const t of [5, 10, 20, 35]) {
  await page.waitForTimeout(t === 5 ? 5000 : (t - [5,10,20,35][[5,10,20,35].indexOf(t)-1]) * 1000);
  const vis = await page.getByText('03584L32').first().isVisible().catch(() => false);
  console.log(`t=${t}s data visible: ${vis}`);
  if (vis) break;
}
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/dbg-hang.png' });
await b.close();

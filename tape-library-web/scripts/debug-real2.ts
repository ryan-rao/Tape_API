import { chromium } from '@playwright/test';

const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 200)); });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 200)));
page.on('requestfailed', (r) => console.log('REQFAIL:', r.url().slice(0, 100), r.failure()?.errorText));

await page.goto('http://172.16.12.186:8080/');
for (const wait of [3, 6, 10, 15]) {
  await page.waitForTimeout(wait * 1000);
  const txt = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').slice(0, 200);
  console.log(`t=${wait}s size=${(await page.evaluate(() => document.body.innerHTML.length))} text: ${txt || '(empty)'}`);
  if (txt) break;
}
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/real-dashboard.png' });
await b.close();
console.log('SHOT_DONE');

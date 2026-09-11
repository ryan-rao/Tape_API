import { chromium } from '@playwright/test';
const BASE = 'http://172.16.12.186:8080';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE_ERR:', m.text().slice(0, 120)); });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

await page.goto(BASE + '/tests', { waitUntil: 'domcontentloaded' });
await page.getByText('Mount Tape').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(3500);
console.log('Select 个数:', await page.locator('.ant-select-selector').count());
// 逐个点开看哪个是 Tape/Slot（含 placeholder "选择槽位"）
const n = await page.locator('.ant-select-selector').count();
for (let i = 0; i < n; i++) {
  const ph = await page.locator('.ant-select-selector').nth(i).locator('.ant-select-selection-placeholder').allInnerTexts().catch(() => []);
  const val = await page.locator('.ant-select-selector').nth(i).locator('.ant-select-selection-item').allInnerTexts().catch(() => []);
  console.log(`  Select[${i}] placeholder=${JSON.stringify(ph)} value=${JSON.stringify(val)}`);
}
// API 请求跟踪
const reqs: string[] = [];
page.on('request', (r) => { if (r.url().includes('/api/')) reqs.push(r.url().replace(BASE, '')); });
await page.reload({ waitUntil: 'domcontentloaded' });
await page.getByText('Mount Tape').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(3500);
console.log('API 请求:', JSON.stringify(reqs.slice(0, 12)));
await b.close();

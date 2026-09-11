import { chromium } from '@playwright/test';

const BASE = 'http://172.16.12.186:8080';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 200)));

await page.goto(BASE + '/');
await page.getByText('Tape Libraries').first().waitFor({ timeout: 25000 });
await page.getByText('Library Overview').first().click();
await page.getByText('03584L32').first().waitFor({ timeout: 25000 });
await page.getByText('Drive Status').first().click();
await page.getByText('ULT3580-TDA').first().waitFor({ timeout: 20000 });

await page.getByText('API Logs').first().click();
await page.getByText('API Call Logs').first().waitFor({ timeout: 10000 });
await page.waitForTimeout(2000);
const rows = await page.locator('tbody tr').count();
console.log('log rows:', rows);
const paths = await page.locator('tbody tr td:nth-child(3)').allTextContents();
console.log('paths:', JSON.stringify(paths.slice(0, 8)));

if (rows > 0) {
  await page.locator('tbody tr').first().getByText('查看').click();
  await page.getByText('响应输出（Response）').waitFor({ timeout: 5000 });
  await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/real-apilogs-detail.png' });
  await page.keyboard.press('Escape');
}
await page.waitForTimeout(500);
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/real-apilogs.png' });
console.log(rows > 0 ? 'REAL_APILOGS_OK' : 'REAL_APILOGS_EMPTY');
await b.close();

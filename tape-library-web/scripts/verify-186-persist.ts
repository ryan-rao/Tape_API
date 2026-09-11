import { chromium } from '@playwright/test';
const BASE = 'http://172.16.12.186:8080';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));
// 1. 产生真实 API 日志
await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
await page.getByText('Tape Libraries').first().waitFor({ timeout: 30000 });
await page.getByText('Library Overview').first().click();
await page.getByText('03584L32').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(2500); // persist 防抖写盘
const bytes = await page.evaluate(() => localStorage.getItem('tape-api-logs')?.length ?? -1);
console.log('localStorage bytes:', bytes);
// 2. 整页刷新后进 API Logs
await page.reload({ waitUntil: 'domcontentloaded' });
await page.getByText('03584L32').first().waitFor({ timeout: 30000 });
await page.getByText('API Logs').first().click();
await page.getByText('API Call Logs').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(2000);
const rows = await page.locator('tbody tr').count();
console.log('history rows after reload:', rows);
const sw = await page.getByText('10s 刷新').count();
console.log('auto-refresh switch:', sw);
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/real-apilogs-history.png' });
console.log(rows > 0 ? 'PERSIST_OK' : 'PERSIST_FAIL');
await b.close();

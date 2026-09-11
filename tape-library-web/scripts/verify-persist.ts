import { chromium } from '@playwright/test';

const BASE = 'http://localhost:5173';
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1600, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

// 1. 产生日志
await page.goto(BASE + '/');
await page.getByText('03584L32').first().waitFor({ timeout: 20000 }); console.log('step3: reloaded OK');
await page.getByText('Library Overview').first().click();
await page.getByText('03584L32').first().waitFor({ timeout: 15000 }); console.log('step2: libraries OK');
await page.waitForTimeout(2500); // 等 persist 防抖写盘

// 2. 整页刷新（模拟用户按 F5）
await page.reload({ waitUntil: "domcontentloaded" });
await page.getByText('03584L32').first().waitFor({ timeout: 20000 }); console.log('step3: reloaded OK');
await page.getByText('API Logs').first().click();
await page.getByText('API Call Logs').first().waitFor({ timeout: 10000 });
await page.waitForTimeout(1500);
const rows = await page.locator('tbody tr').count();
console.log('rows after reload:', rows);

// 3. 自动刷新开关存在
const sw = await page.getByText('10s 刷新').count();
console.log('auto-refresh switch:', sw);
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/14-ApiLogs-persist.png' });
console.log(rows > 0 ? 'PERSIST_OK' : 'PERSIST_FAIL');
await b.close();

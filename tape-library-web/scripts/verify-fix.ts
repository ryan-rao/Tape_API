import { chromium } from '@playwright/test';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

// Dashboard 停 35s，让 10s 轮询跑 3 轮（会产生 6+ 条大 status 日志）
await page.goto('http://172.16.12.186:8080/', { waitUntil: 'domcontentloaded' });
await page.getByText('Tape Libraries').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(35000);
const bytes = await page.evaluate(() => localStorage.getItem('tape-api-logs')?.length ?? -1);
console.log('localStorage after 3 polls:', bytes, 'bytes');

// 切到 /libraries 测加载速度
const t0 = Date.now();
await page.getByText('Library Overview').first().click();
await page.getByText('03584L32').first().waitFor({ timeout: 30000 });
console.log('libraries data visible in', Date.now() - t0, 'ms');
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/verify-fix.png' });
await b.close();

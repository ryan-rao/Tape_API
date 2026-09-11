import { chromium } from '@playwright/test';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

// 先植入旧版超大日志（模拟用户浏览器：tape-api-logs 约 5MB）
await page.goto('http://172.16.12.186:8080/', { waitUntil: 'domcontentloaded' });
await page.evaluate(() => {
  const big = { success: true, code: 'OK', data: 'x'.repeat(400000) };
  const arr = Array.from({ length: 13 }, (_, i) => ({ id: i + 1, ts: new Date().toISOString(), method: 'GET', path: '/api/v1/libraries/sg1/status', status: 200, ok: true, code: 'OK', duration_ms: 1100, response: big }));
  localStorage.setItem('tape-api-logs', JSON.stringify(arr));
});
console.log('planted old junk:', (await page.evaluate(() => localStorage.getItem('tape-api-logs')!.length)), 'bytes');

// 整页刷新，测首页加载耗时
const t0 = Date.now();
await page.reload({ waitUntil: 'domcontentloaded' });
await page.getByText('Tape Libraries').first().waitFor({ timeout: 30000 });
console.log('homepage visible in', Date.now() - t0, 'ms');
console.log('old junk removed:', await page.evaluate(() => localStorage.getItem('tape-api-logs') === null));
// 再等一轮 10s 轮询确认不卡
await page.waitForTimeout(12000);
const vis = await page.getByText('Tape Drives').first().isVisible().catch(() => false);
console.log('after 10s poll still responsive:', vis);
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/verify-fix2.png' });
await b.close();

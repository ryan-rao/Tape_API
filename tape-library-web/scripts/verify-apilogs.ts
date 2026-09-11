import { chromium } from '@playwright/test';

const BASE = 'http://localhost:5173';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 200)));

// 首次加载（Dashboard 产生调用）
await page.goto(BASE + '/');
await page.getByText('Tape Libraries').first().waitFor({ timeout: 15000 });

// 侧边栏客户端导航（不刷新页面，日志保留）
await page.getByText('Library Overview').first().click();
await page.getByText('03584L32').first().waitFor({ timeout: 15000 });
await page.getByText('Tapes').first().click();
await page.waitForTimeout(1500);

// 打开 API Logs
await page.getByText('API Logs').first().click();
await page.getByText('API Call Logs').first().waitFor({ timeout: 10000 });
await page.waitForTimeout(1000);
const rows = await page.locator('tbody tr').count();
console.log('log rows:', rows);

if (rows > 0) {
  await page.locator('tbody tr').first().getByText('查看').click();
  await page.getByText('响应输出（Response）').waitFor({ timeout: 5000 });
  console.log('drawer OK, pre blocks:', await page.locator('.ant-drawer pre').count());
  await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/14-ApiLogs-detail.png' });
  await page.keyboard.press('Escape');
}
await page.waitForTimeout(500);
await page.screenshot({ path: '/root/.openclaw/workspace/tape-library-web/screenshots/14-ApiLogs.png' });
console.log(rows > 0 ? 'APILOGS_OK' : 'APILOGS_EMPTY');
await b.close();

import { chromium } from '@playwright/test';
const BASE = 'http://172.16.12.186:8080';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

await page.goto(BASE + '/tests', { waitUntil: 'domcontentloaded' });
await page.getByText('Mount Tape').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(2500);
// ② Tape/Slot 下拉选择 IBM015LA
await page.locator('.ant-select-selector').nth(1).click();
await page.waitForTimeout(500);
await page.locator('.ant-select-item').filter({ hasText: 'IBM015LA' }).first().click();
await page.waitForTimeout(300);
// 触发确认流程
for (const label of ['Confirm', 'Run', 'Execute', 'Start']) {
  const btn = page.getByRole('button', { name: new RegExp(label, 'i') }).first();
  if (await btn.isEnabled().catch(() => false)) { await btn.click(); break; }
}
await page.waitForTimeout(1000);
// 二次确认弹窗（Barcode）
const modal = page.locator('.ant-modal');
if (await modal.count()) {
  const input = modal.locator('input');
  if (await input.count()) { await input.fill('IBM015LA'); await page.waitForTimeout(200); }
  await modal.getByRole('button', { name: /ok|confirm|确/i }).first().click();
}
// 等机械臂操作完成（~20s）
await page.waitForTimeout(22000);
const success = await page.getByText(/Mount PASS/).count();
const fail = await page.getByText(/Operation Failed/).count();
console.log('成功消息 Mount PASS:', success, '| 失败消息:', fail);
await page.screenshot({ path: 'screenshots/verify-mount.png' });
// Drives 页验证装载
await page.goto(BASE + '/drives', { waitUntil: 'domcontentloaded' });
await page.getByText('ULT3580-TDA').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(3000);
console.log('Drives 页 IBM015LA:', await page.getByText('IBM015LA').count(), '| LOADED 标签:', await page.getByText('LOADED').count());
await page.screenshot({ path: 'screenshots/verify-mount-drives.png' });
await b.close();
console.log('MOUNT_E2E_DONE');

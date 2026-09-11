import { chromium } from '@playwright/test';
const BASE = 'http://172.16.12.186:8080';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

await page.goto(BASE + '/tests', { waitUntil: 'domcontentloaded' });
await page.getByText('Mount Tape').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(7000);
// ① 点槽位下拉（含"选择槽位"placeholder 的那个）
await page.locator('.ant-select-selector', { hasText: '选择槽位' }).first().click();
await page.waitForTimeout(800);
const items = await page.locator('.ant-select-dropdown .ant-select-item').allInnerTexts();
console.log('槽位项:', JSON.stringify(items));
if (!items.length) { console.log('FAIL: 无槽位可选'); await b.close(); process.exit(1); }
await page.locator('.ant-select-dropdown .ant-select-item').first().click();
await page.waitForTimeout(400);
// ② 点执行按钮 Mount Tape（button，非下拉）
await page.locator('button', { hasText: 'Mount Tape' }).first().click();
await page.waitForTimeout(1200);
// ③ 确认弹窗（可能要输 barcode）
const modal = page.locator('.ant-modal');
if (await modal.count()) {
  const input = modal.locator('input');
  if (await input.count()) {
    const bc = items[0].split('/')[0].trim();
    await input.fill(bc);
    console.log('填入 barcode:', bc);
    await page.waitForTimeout(300);
  }
  await page.locator('.ant-modal button').filter({ hasText: /OK|确|Confirm/ }).first().click();
}
// ④ 立即抓 toast（带机已有磁带 → 应显示 Drive Already Loaded）
for (let i = 0; i < 20; i++) {
  await page.waitForTimeout(1000);
  const toasts = await page.locator('.ant-message-notice').allInnerTexts();
  if (toasts.length) { console.log('TOAST:', JSON.stringify(toasts)); break; }
  if (i === 19) console.log('TOAST: 无消息出现');
}
await page.screenshot({ path: 'screenshots/mount4-result.png' });
await b.close();

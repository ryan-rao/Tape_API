import { chromium } from '@playwright/test';
const BASE = 'http://172.16.12.186:8080';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

await page.goto(BASE + '/tests', { waitUntil: 'domcontentloaded' });
await page.getByText('Mount Tape').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(2500);
console.log('按钮:', JSON.stringify(await page.locator('button:visible').allInnerTexts()));
// ② Tape/Slot 下拉（第2个 Select）——带机里有带，槽6空；先看可选项
await page.locator('.ant-select-selector').nth(1).click();
await page.waitForTimeout(600);
console.log('下拉项:', JSON.stringify(await page.locator('.ant-select-item:visible').allInnerTexts()));
await page.keyboard.press('Escape');
await page.screenshot({ path: 'screenshots/mount2-step1.png' });
await b.close();

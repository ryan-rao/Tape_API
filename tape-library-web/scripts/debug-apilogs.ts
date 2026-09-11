import { chromium } from '@playwright/test';

const b = await chromium.launch();
const page = await b.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 200)));
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 200)); });

await page.goto('http://localhost:5173/libraries');
await page.getByText('03584L32').first().waitFor({ timeout: 15000 });
await page.goto('http://localhost:5173/api-logs');
await page.getByText('API Call Logs').first().waitFor({ timeout: 10000 });
await page.waitForTimeout(1000);
console.log('rows:', await page.locator('tbody tr').count());
console.log('row html:', (await page.locator('tbody tr').first().innerHTML().catch(() => 'N/A')).slice(0, 400));
const btns = await page.locator('tbody button').allTextContents().catch(() => []);
console.log('row buttons:', JSON.stringify(btns));
await b.close();

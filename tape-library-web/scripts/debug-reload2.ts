import { chromium } from '@playwright/test';

const b = await chromium.launch();
const page = await b.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 300)); });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 300)));
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
await page.getByText('Tape Libraries').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(2500);
await page.evaluate(() => (location.hash = ''));
// 客户端导航到 /libraries
await page.getByText('Library Overview').first().click();
await page.getByText('03584L32').first().waitFor({ timeout: 15000 });
console.log('nav OK, url:', page.url());
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForTimeout(6000);
console.log('url:', page.url());
console.log('TEXT:', (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').slice(0, 250) || '(empty)');
await b.close();

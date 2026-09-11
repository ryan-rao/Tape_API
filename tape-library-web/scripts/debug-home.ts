import { chromium } from '@playwright/test';

const b = await chromium.launch();
const page = await b.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 250)); });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 250)));
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(6000);
console.log('TEXT:', (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').slice(0, 300) || '(empty)');
await b.close();

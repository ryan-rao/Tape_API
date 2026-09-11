import { chromium } from '@playwright/test';

const b = await chromium.launch();
const page = await b.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 300)); });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 300)));
await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded' });
await page.getByText('Tape Libraries').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(2500);
const stored = await page.evaluate(() => localStorage.getItem('tape-api-logs')?.length ?? -1);
console.log('localStorage bytes:', stored);
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForTimeout(6000);
console.log('TEXT after reload:', (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').slice(0, 200) || '(empty)');
await b.close();

import { chromium } from '@playwright/test';

const b = await chromium.launch();
const page = await b.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 300)); });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 300)));
page.on('requestfailed', (r) => console.log('REQFAIL:', r.url().slice(0, 120), r.failure()?.errorText));

await page.goto('http://172.16.12.186:8080/');
await page.waitForTimeout(5000);
console.log('=== body ===');
console.log((await page.evaluate(() => document.body.innerText)).slice(0, 300).replace(/\n/g, ' | '));
console.log('=== html size ===', (await page.evaluate(() => document.body.innerHTML.length)));
await b.close();

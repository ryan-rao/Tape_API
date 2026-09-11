import { chromium } from '@playwright/test';
import fs from 'fs';

fs.mkdirSync('/root/.openclaw/workspace/tape-library-web/screenshots', { recursive: true });
const OUT = '/root/.openclaw/workspace/tape-library-web/screenshots';
const BASE = 'http://localhost:5173';

const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
const shot = (n: string) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: false });

// 01 Dashboard
await page.goto(BASE + '/');
await page.getByText('Tape Libraries').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(1500);
await shot('01-Dashboard');

// 02 Libraries
await page.goto(BASE + '/libraries');
await page.getByText('03584L32').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('02-Libraries');

// 03 Library Detail（槽位可视化）
await page.goto(BASE + '/libraries/sg1');
await page.getByText('Slot Visualization').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('03-LibraryDetail-Slots');

// 04 Slot 详情弹窗
await page.getByText('IBM006LA').first().click();
await page.getByText('Slot Information').waitFor({ timeout: 5000 });
await page.waitForTimeout(500);
await shot('04-SlotDetail-Modal');
await page.keyboard.press('Escape');

// 05 Drives
await page.goto(BASE + '/drives');
await page.getByText('ULT3580-TDA').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('05-Drives');

// 06 Drive Detail
await page.goto(BASE + '/drives/nst1');
await page.getByText('Loaded Tape').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('06-DriveDetail');

// 07 Tapes
await page.goto(BASE + '/tapes');
await page.getByText('IBM006LA').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('07-Tapes');

// 08 Test Center 初始
await page.goto(BASE + '/tests');
await page.getByText('Safety Policy').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('08-TestCenter');

// 09 Mount 确认弹窗
await page.locator('.ant-select-selector').nth(1).click();
await page.locator('.ant-select-item-option', { hasText: 'IBM015LA / Slot 6' }).first().click();
await page.getByRole('button', { name: 'Mount Tape' }).click();
await page.getByText('Confirm Mount').first().waitFor({ timeout: 5000 });
await page.waitForTimeout(500);
await shot('09-Mount-Confirm');
await page.getByRole('button', { name: 'Confirm Mount' }).click();
await page.getByText(/Mount PASS/).first().waitFor({ timeout: 30000 });
await page.waitForTimeout(500);
await shot('10-Mount-PASS');

// 11 Write 二次确认（Barcode）
await page.locator('.ant-select-selector').nth(3).click();
await page.locator('.ant-select-item-option', { hasText: 'Write Test (verify)' }).first().click();
await page.getByRole('button', { name: 'Write Test (verify)' }).click();
await page.getByPlaceholder('Enter tape barcode').waitFor({ timeout: 5000 });
await page.getByPlaceholder('Enter tape barcode').fill('WRONG-9999');
await page.waitForTimeout(500);
await shot('11-Write-Confirm-WrongBarcode');

// 12 Operations
await page.goto(BASE + '/operations');
await page.getByText('Mount').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('12-Operations');

// 13 Audit
await page.goto(BASE + '/audit');
await page.getByText('Command ID').first().waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
await shot('13-Audit');

await b.close();
console.log('DONE:', fs.readdirSync(OUT).join(', '));

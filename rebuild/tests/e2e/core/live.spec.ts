import { test, expect } from '../../../apps/web/node_modules/@playwright/test';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

// Opt-in coordinated runtime only. Never bootstraps or migrates a database.
test('coordinated local API persists case and exact artifact bytes across browser reload', async ({ page }) => {
  test.skip(!process.env.OMNIFORGE_UI_TOKEN_FILE, 'Requires Main-approved backend runtime and exact private token path.');
  const token = (await readFile(process.env.OMNIFORGE_UI_TOKEN_FILE!, 'utf8')).trim();
  const title = `UI synthetic proof ${Date.now()}`;
  const bytes = Buffer.from('Synthetic evidence only.\nUTF-8: café.\nNo real source data.\n');
  const hash = createHash('sha256').update(bytes).digest('hex');
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('Access token').fill(token); await page.getByRole('button', { name: 'Connect to workspace' }).click();
  await page.getByRole('button', { name: '+ New case', exact: true }).click();
  await page.getByLabel('Case title').fill(title); await page.getByLabel('Objective').fill('Verify synthetic browser/API/database persistence and exact byte transport.');
  await page.getByRole('button', { name: 'Create case', exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await page.getByRole('button', { name: '+ Import artifact', exact: true }).click();
  await page.getByLabel('Source file').setInputFiles({ name: 'ui-synthetic-proof.txt', mimeType: 'text/plain', buffer: bytes });
  await page.getByRole('button', { name: 'Import artifact', exact: true }).click();
  await page.getByRole('button', { name: /ui-synthetic-proof.txt/ }).click();
  await expect(page.getByText(hash, { exact: true })).toBeVisible();
  await expect(page.getByText('Not recorded', { exact: true })).toBeVisible();
  await page.getByLabel('End', { exact: true }).fill('9'); await page.getByRole('button', { name: 'Read range' }).click();
  await expect(page.getByLabel('Exact range preview')).toHaveText('Synthetic');
  await page.getByRole('button', { name: 'Hex', exact: true }).click(); await expect(page.getByLabel('Exact range preview')).toContainText('53 79 6e 74 68 65 74 69 63');
  await page.screenshot({ path: 'test-results/live-detail.png', fullPage: true });
  await page.reload(); await expect(page.getByLabel('Access token')).toHaveValue('');
  await page.getByLabel('Access token').fill(token); await page.getByRole('button', { name: 'Connect to workspace' }).click();
  // Small retained fixture corpus; explicitly follow pages if earlier fixtures fill one.
  while (!(await page.getByRole('heading', { name: title, exact: true }).count()) && await page.getByRole('button', { name: 'Load more cases' }).count()) await page.getByRole('button', { name: 'Load more cases' }).click();
  await page.getByRole('button', { name: new RegExp(title) }).click();
  await page.getByRole('button', { name: /ui-synthetic-proof.txt/ }).click();
  await expect(page.getByText(hash, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Read range' }).click(); await expect(page.getByLabel('Exact range preview')).toHaveText(bytes.toString('utf8'));
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await page.getByLabel('Access token').fill('synthetic-invalid'); await page.getByRole('button', { name: 'Connect to workspace' }).click();
  await expect(page.getByRole('alert')).toBeVisible(); expect(errors).toEqual([]);
});

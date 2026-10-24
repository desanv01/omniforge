import { test, expect } from '../../../apps/web/node_modules/@playwright/test';
import type { Case, ArtifactAssociation } from '../../../packages/contracts/generated/types.gen';

const example: Case = { id: 'synthetic-case', title: 'Harbor water quality', objective: 'Compare the original sampling notes and preserve their source context.', revision: 1, policy_profile_ref: 'local-read-only-v1', status: 'open', created_at: '2026-10-23T08:00:00Z', updated_at: '2026-10-23T08:00:00Z' };
const source: ArtifactAssociation = { id: 'synthetic-association', artifact_id: 'synthetic-artifact', case_id: example.id, source_id: 'sampling-notes-01', original_name: 'sampling-notes.txt', bytes: 11, media_type: 'text/plain', sha256: 'b'.repeat(64), captured_at: null, imported_at: '2026-10-23T08:05:00Z', publication_status: 'committed', revision: 1, warnings: [] };

test('synthetic browser case/import/range flow and responsive layout', async ({ page }) => {
  let cases: Case[] = [], artifacts: ArtifactAssociation[] = [];
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url());
    expect(request.headers().authorization).toBe('Bearer synthetic-ui-token');
    expect(url.href).not.toContain('synthetic-ui-token');
    if (url.pathname.endsWith('/ranges')) return route.fulfill({ contentType: 'application/octet-stream', body: Buffer.from('hello world').subarray(Number(url.searchParams.get('start_byte')), Number(url.searchParams.get('end_byte'))) });
    if (url.pathname.endsWith('/artifacts') && request.method() === 'POST') {
      expect(url.searchParams.get('expected_revision')).toBe('1'); expect(request.headers()['idempotency-key']).toBeTruthy();
      artifacts = [source]; cases[0] = { ...example, revision: 2 }; return route.fulfill({ json: source });
    }
    if (url.pathname.endsWith('/artifacts')) return route.fulfill({ json: { items: artifacts, next_cursor: null } });
    if (url.pathname.endsWith('/cases') && request.method() === 'POST') { cases = [example]; return route.fulfill({ json: example }); }
    if (url.pathname.endsWith('/cases')) return route.fulfill({ json: { items: cases, next_cursor: null } });
    return route.fulfill({ json: cases[0] });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Open your workspace' })).toBeVisible();
  await page.getByLabel('Access token').fill('synthetic-ui-token'); await page.getByRole('button', { name: 'Connect to workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Start with a question' })).toBeVisible();
  await page.getByRole('button', { name: '+ New case', exact: true }).click();
  await page.getByLabel('Case title').fill(example.title); await page.getByLabel('Objective').fill(example.objective);
  await page.getByRole('button', { name: 'Create case', exact: true }).click();
  await expect(page.getByRole('heading', { name: example.title, exact: true })).toBeVisible();
  await page.getByRole('button', { name: '+ Import artifact', exact: true }).click();
  await page.getByLabel('Source file').setInputFiles({ name: source.original_name, mimeType: source.media_type, buffer: Buffer.from('hello world') });
  await page.getByRole('button', { name: 'Import artifact', exact: true }).click();
  await page.getByRole('button', { name: /sampling-notes.txt/ }).click();
  await expect(page.getByText('Not recorded', { exact: true })).toBeVisible();
  await page.getByLabel('End', { exact: true }).fill('5'); await page.getByRole('button', { name: 'Read range' }).click();
  await expect(page.getByLabel('Exact range preview')).toHaveText('hello');
  await expect(page.getByText(/Partial byte range/)).toBeVisible();
  await page.getByRole('button', { name: 'Hex', exact: true }).click(); await expect(page.getByLabel('Exact range preview')).toContainText('68 65 6c 6c 6f');
  for (const width of [1440, 768, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole('button', { name: 'Read range' })).toBeVisible();
    if (width === 375) await page.screenshot({ path: 'test-results/synthetic-mobile.png', fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: 'test-results/synthetic-detail.png', fullPage: true });
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await expect(page.getByLabel('Access token')).toHaveValue(''); expect(errors).toEqual([]);
});

test('structured auth error stays actionable', async ({ page }) => {
  await page.route('**/api/v1/cases*', route => route.fulfill({ status: 401, json: { category: 'unauthenticated', code: 'auth_required', message: 'Access token not recognized.', request_id: 'synthetic-request', retryable: false } }));
  await page.goto('/'); await page.getByLabel('Access token').fill('synthetic-invalid'); await page.getByRole('button', { name: 'Connect to workspace' }).click();
  await expect(page.getByRole('alert')).toContainText('Access token not recognized.'); await expect(page.getByRole('alert')).toContainText('synthetic-request');
});

test('partial pagination, pending/empty/unsupported artifacts and interrupted reads are explicit', async ({ page }) => {
  let failRead = false;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/ranges')) return failRead ? route.abort('failed') : route.fulfill({ contentType: 'application/octet-stream', body: Buffer.from([0, 255]) });
    if (url.pathname.endsWith('/artifacts')) return route.fulfill({ json: { items: url.searchParams.has('cursor') ? [{ ...source, id: 'binary', original_name: 'binary.bin', media_type: 'application/octet-stream', bytes: 2 }] : [{ ...source, id: 'pending', original_name: 'pending.txt', publication_status: 'pending' }, { ...source, id: 'empty', original_name: 'empty.txt', bytes: 0 }], next_cursor: url.searchParams.has('cursor') ? null : 'synthetic-next' } });
    if (url.pathname.endsWith('/cases')) return route.fulfill({ json: { items: [example], next_cursor: null } });
    return route.fulfill({ json: example });
  });
  await page.goto('/'); await page.getByLabel('Access token').fill('synthetic'); await page.getByRole('button', { name: 'Connect to workspace' }).click();
  await page.getByRole('button', { name: /Harbor water quality/ }).click();
  await expect(page.getByText('Partial list', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /pending.txt/ }).click(); await expect(page.getByText(/Publication pending/)).toBeVisible(); await expect(page.getByRole('button', { name: 'Read range' })).toHaveCount(0);
  await page.getByRole('button', { name: /empty.txt/ }).click(); await expect(page.getByText(/Complete empty artifact/)).toBeVisible();
  await page.getByRole('button', { name: 'Load more artifacts' }).click(); await page.getByRole('button', { name: /binary.bin/ }).click();
  await page.getByRole('button', { name: 'Read range' }).click(); await expect(page.getByText(/Text preview is unsupported/)).toBeVisible();
  await page.getByRole('button', { name: 'Hex', exact: true }).click(); await expect(page.getByLabel('Exact range preview')).toContainText('00 ff');
  failRead = true; await page.getByRole('button', { name: 'Read range' }).click(); await expect(page.getByRole('alert')).toContainText('Connection interrupted'); await expect(page.getByLabel('Exact range preview')).toHaveCount(0);
});

test('active import cannot be closed and interruption retains uncertain outcome', async ({ page }) => {
  let uploadStarted = false;
  const keys: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/artifacts') && route.request().method() === 'POST') { uploadStarted = true; keys.push(route.request().headers()['idempotency-key']); if (keys.length > 1) await route.abort('failed'); return; }
    if (url.pathname.endsWith('/artifacts')) return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: url.pathname.endsWith('/cases') ? { items: [example], next_cursor: null } : example });
  });
  await page.goto('/'); await page.getByLabel('Access token').fill('synthetic'); await page.getByRole('button', { name: 'Connect to workspace' }).click();
  await page.getByRole('button', { name: /Harbor water quality/ }).click(); await page.getByRole('button', { name: '+ Import artifact', exact: true }).click();
  await page.getByLabel('Source file').setInputFiles({ name: 'fixture.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic') });
  await page.getByRole('button', { name: 'Import artifact', exact: true }).click();
  await expect.poll(() => uploadStarted).toBe(true);
  await expect(page.getByRole('button', { name: 'Close import', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Interrupt upload' }).click();
  await expect(page.getByRole('alert')).toContainText('Publication may have completed');
  await expect(page.getByRole('button', { name: 'Retry import', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Retry import', exact: true }).click();
  await expect.poll(() => keys.length).toBe(2); expect(keys[1]).toBe(keys[0]);
  await expect(page.getByRole('alert')).toContainText('Connection interrupted');
});

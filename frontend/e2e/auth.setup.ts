import { expect, test as setup } from '@playwright/test';

import { AUTH_STORAGE_PATH, login } from './auth';

// Login is rate-limited per subject, so authenticate once per invocation and
// share the storage state instead of signing in before every test.
setup('authenticate as the seeded e2e administrator', async ({ page }, testInfo) => {
  // The redirect alone is not catalog readiness. The first authenticated
  // request admits the configured runtime in this API process; a preflight in
  // another process cannot warm that admission. Keep this request alive until
  // it completes, within the existing setup test budget, before closing the
  // setup page and handing off to the independent desktop/mobile contexts.
  const catalogResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname === '/api/v1/workflows/',
    { timeout: testInfo.timeout },
  );
  const [, response] = await Promise.all([login(page), catalogResponse]);
  // Match the first response regardless of status so HTTP failures fail here,
  // instead of waiting for a later successful retry to hide the initial error.
  expect(response.status()).toBe(200);
  const catalog = await response.json();
  expect(catalog.ok).toBe(true);
  expect(Array.isArray(catalog.workflows)).toBe(true);
  expect(catalog.workflows.length).toBeGreaterThan(0);
  await expect(
    page.getByRole('status', { name: 'Loading workflows' }),
  ).toBeHidden();
  await page.context().storageState({ path: AUTH_STORAGE_PATH });
});

import { expect, request, test } from '@playwright/test';

import { loadManifest } from './manifest';

const STAFF_BASE = 'http://localhost:4201';
const PLAYER_BASE = 'http://localhost:4200';

test.describe('Staff journey', () => {
  test('create invite → player submits → staff confirms', async ({
    page,
    context,
  }) => {
    const manifest = loadManifest();

    // ---- 1. Staff signs in on the staff app -----------------------------
    await page.goto(`${STAFF_BASE}/login`);
    await page.getByLabel('Username or email').fill(manifest.staff.username);
    await page.getByLabel('Password').fill(manifest.staff.password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(`${STAFF_BASE}/`);

    // ---- 2. Staff visits Invites and mints a fresh one ------------------
    await page.goto(`${STAFF_BASE}/invites`);
    await page.getByLabel('Team').selectOption({ index: 1 });
    await page.getByRole('button', { name: /Create invite/i }).click();

    // The new invite lands at the top of the pending list; grab its URL
    // via the "Show QR" panel.
    const firstItem = page.locator('.list-group-item').first();
    await firstItem.getByRole('button', { name: /Show QR/i }).click();
    const urlText = await firstItem.locator('code').first().innerText();
    expect(urlText).toContain('/invite/');

    // ---- 3. Player (isolated context) accepts the invite ----------------
    const playerContext = await context.browser()!.newContext();
    await playerContext.grantPermissions(['geolocation'], { origin: PLAYER_BASE });
    await playerContext.setGeolocation({ latitude: 46.068374, longitude: 23.571797 });
    const playerPage = await playerContext.newPage();
    await playerPage.goto(urlText);

    const suffix = Math.random().toString(36).slice(2, 8);
    await playerPage.getByLabel('Username').fill(`e2e-staff-player-${suffix}`);
    await playerPage.getByLabel('Email').fill(`e2e-staff-player-${suffix}@example.com`);
    await playerPage.getByLabel('Password').fill('e2e-player-pass');
    await playerPage
      .getByRole('button', { name: /Create account & accept/i })
      .click();
    await expect(playerPage).toHaveURL(PLAYER_BASE + '/');

    // ---- 4. Player submits the tower challenge --------------------------
    await playerPage.goto(`${PLAYER_BASE}/tower/${manifest.tower_id}`);
    await playerPage.getByRole('button', { name: /Submit challenge/i }).click();
    await expect(playerPage.getByText(/Submission received/i)).toBeVisible();
    await playerContext.close();

    // ---- 5. Staff reviews and confirms ----------------------------------
    await page.goto(`${STAFF_BASE}/`);
    const pendingCard = page
      .locator('.card')
      .filter({ hasText: manifest.tower_name })
      .first();
    await expect(pendingCard).toBeVisible();
    await pendingCard.getByRole('button', { name: /Confirm/i }).click();
    // After confirm, the card is removed from the queue.
    await expect(
      page.locator('.card').filter({ hasText: manifest.tower_name }),
    ).toHaveCount(0);

    // ---- 6. Verify the tower color updated: the /api/towers/ ownership now
    //         shows the team color. Easier + more stable than driving Leaflet.
    const api = await request.newContext();
    const resp = await api.get('http://localhost:8000/api/towers/');
    expect(resp.ok()).toBeTruthy();
    const towers: Array<{ id: number; ownership: { color?: string } }> = await resp.json();
    const ours = towers.find((t) => t.id === manifest.tower_id);
    expect(ours?.ownership?.color).toBeTruthy();
  });
});

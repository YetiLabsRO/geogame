import { expect, test } from '@playwright/test';

import { loadManifest } from './manifest';

test.describe('Player journey', () => {
  test('invite → register → map → submit challenge', async ({ page, context }) => {
    const manifest = loadManifest();

    // Mock geolocation so the tower-detail page passes the 50m proximity check.
    await context.grantPermissions(['geolocation'], { origin: 'http://localhost:4200' });
    await context.setGeolocation({ latitude: 46.068374, longitude: 23.571797 });

    // 1. Hit the invite URL unauthenticated and accept by creating an account.
    await page.goto(manifest.invite.url);
    await expect(page.getByText(manifest.team_name, { exact: false })).toBeVisible();

    await page.getByLabel('Username').fill(manifest.player.username);
    await page.getByLabel('Email').fill(manifest.player.email);
    await page.getByLabel('Password').fill(manifest.player.password);
    await page.getByRole('button', { name: /Create account & accept/i }).click();

    // 2. Land on the map. Navbar should show the new username.
    await expect(page).toHaveURL('http://localhost:4200/');
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();

    // 3. Navigate to the tower detail page via direct URL (map click opens a
    //    Leaflet popup which is painful to drive — direct nav is the stable path).
    await page.goto(`http://localhost:4200/tower/${manifest.tower_id}`);
    await expect(page.getByRole('heading', { name: manifest.tower_name })).toBeVisible();
    await expect(page.getByText('In range', { exact: false })).toBeVisible();

    // 4. Submit the challenge (photo is optional).
    await page.getByRole('button', { name: /Submit challenge/i }).click();
    await expect(page.getByText(/Submission received/i)).toBeVisible();
  });
});

import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for the cercetador Angular apps.
 *
 * The tests expect a running Django backend on http://localhost:8000 and
 * the player (4200) + staff (4201) Angular dev servers already up with the
 * proxy configs from projects/{player,staff}/../proxy.conf.json.
 *
 * Because Django needs a pre-seeded fixture (a Game, at least one Tower,
 * Challenges, a staff user, and a team for the player to join), starting
 * the servers from inside Playwright is deliberately opt-in via the
 * PLAYWRIGHT_MANAGED env var — CI wires that up; local runs bring their
 * own stack. See .claude/guidelines.md / README for fixture bootstrap.
 */

const managed = process.env.PLAYWRIGHT_MANAGED === '1';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',

  use: {
    baseURL: 'http://localhost:4200',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  ...(managed
    ? {
        webServer: [
          {
            command:
              'cd .. && /home/yeti/.virtualenvs/cercetador/bin/python manage.py runserver 8000',
            url: 'http://localhost:8000/health/',
            reuseExistingServer: false,
            timeout: 60_000,
          },
          {
            command: 'npm run start:player',
            url: 'http://localhost:4200',
            reuseExistingServer: true,
            timeout: 120_000,
          },
          {
            command: 'npm run start:staff',
            url: 'http://localhost:4201',
            reuseExistingServer: true,
            timeout: 120_000,
          },
        ],
      }
    : {}),
});

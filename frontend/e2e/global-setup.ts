import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';

const exec = promisify(execFile);

const PYTHON =
  process.env.CERCETADOR_PYTHON ?? '/home/yeti/.virtualenvs/cercetador/bin/python';
const MANAGE_PY_CWD = join(__dirname, '..', '..');
const MANIFEST_PATH = join(__dirname, '.manifest.json');
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:4200';

export default async function globalSetup() {
  const { stdout } = await exec(
    PYTHON,
    ['manage.py', 'seed_e2e_fixture', '--base-url', BASE_URL],
    { cwd: MANAGE_PY_CWD },
  );
  const manifest = JSON.parse(stdout.trim());
  writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2));
  process.env.E2E_MANIFEST = MANIFEST_PATH;
}

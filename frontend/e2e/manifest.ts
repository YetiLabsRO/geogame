import { readFileSync } from 'node:fs';
import { join } from 'node:path';

export interface E2EManifest {
  base_url: string;
  game_id: number;
  session_id: number;
  session_slug: string;
  team_id: number;
  team_name: string;
  group_slug: string;
  tower_id: number;
  tower_name: string;
  staff: { username: string; password: string; token: string };
  invite: { id: number; token: string; url: string };
  player: { username: string; email: string; password: string };
}

const PATH = process.env.E2E_MANIFEST ?? join(__dirname, '.manifest.json');

export function loadManifest(): E2EManifest {
  return JSON.parse(readFileSync(PATH, 'utf-8'));
}

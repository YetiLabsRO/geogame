/**
 * Team color resolution for any map that plots several teams at once —
 * the simulator and session replay both use it.
 *
 * Some payloads carry a team's real color and some don't: the simulator's
 * `state()`/timeline carry `team_id`/`team_name` only, with real colors
 * surfacing opportunistically via the session's realtime
 * `scoreboard.updated` (`SessionScoreboardEntry.team_color`) and
 * `tower.ownership_changed` (`team.team_color`) events, while a recorded
 * Session's replay bundle carries `Team.color` up front. Feed whatever
 * you know to `learn()`; until a team's real color is known, a small
 * deterministic qualitative palette keeps markers distinguishable from
 * the first render. `--team-color` (THEME.md) isn't usable here since
 * several teams' colors are needed on screen at once.
 */

// Kept as plain literals (not theme tokens) — an arbitrary, a priori
// unknown-length set of simultaneous team colors, same rationale as the
// runtime `--team-color` CSS slot being empty by default.
const FALLBACK_PALETTE = [
  '#2F7A4F', // trail green
  '#2C74B3', // lake blue
  '#E07B39', // blaze orange
  '#C0453B', // clay red
  '#8452A6', // heather purple
  '#2E9E8F', // teal
  '#B5892B', // ochre gold
  '#5F6B7A', // slate
];

export class TeamColorResolver {
  private readonly known = new Map<number, string>();
  /** Stable fallback-palette slot per team, assigned on first sight. */
  private readonly order: number[] = [];

  colorFor(teamId: number | null | undefined): string {
    if (teamId === null || teamId === undefined) return '#9AAAB3'; // unowned
    const known = this.known.get(teamId);
    if (known) return known;
    let slot = this.order.indexOf(teamId);
    if (slot === -1) {
      slot = this.order.length;
      this.order.push(teamId);
    }
    return FALLBACK_PALETTE[slot % FALLBACK_PALETTE.length];
  }

  /** Record an authoritative color learned from a realtime event. */
  learn(teamId: number | null | undefined, color: string | null | undefined): void {
    if (teamId === null || teamId === undefined || !color) return;
    this.known.set(teamId, color);
  }
}

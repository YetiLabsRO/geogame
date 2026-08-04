/**
 * Team color resolution for the simulator map (game-simulator-backend UI).
 *
 * The sim's `state()`/timeline payloads carry `team_id`/`team_name` but no
 * color — real team colors only surface opportunistically, via the
 * session's realtime `scoreboard.updated` (`SessionScoreboardEntry.team_color`)
 * and `tower.ownership_changed` (`team.team_color`) events. Until one of
 * those arrives for a given team, fall back to a small deterministic
 * qualitative palette so markers are still distinguishable from the first
 * render. `--team-color` (THEME.md) isn't usable here since several teams'
 * colors are needed on screen at once.
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

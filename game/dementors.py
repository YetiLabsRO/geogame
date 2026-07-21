"""Dementors-mode server economy (mode-dementors capability).

One energy axis drives the whole state machine:

- a dementor within the drain-range bucket drains a wizard's energy
  (divided across a wizard cluster under safety-in-numbers, or applied
  at full rate to everyone under area-drain);
- a wizard drained to 0 flips to DEMENTOR or goes out of play, per
  config;
- a dementor held by a qualifying wizard group regains energy and flips
  back to WIZARD when it crosses the conversion threshold, or is flipped
  outright by the reverse numbers game after a continuous hold.

`run_tick` is the explicit tick entry point, invoked on report ingestion
(no celery/cron): it derives proximity for the session and, when the
mode is enabled, applies the economy. Deltas are time-based
(energy/second × elapsed-since-last-tick, clamped to the freshness
window) so repeated invocations are safe and tests can pin `now`.
"""
import random

from django.db import transaction
from django.utils import timezone

from game.models import (
    FLIP_CAUSE_CONVERSION,
    FLIP_CAUSE_DIED,
    FLIP_CAUSE_DRAINED,
    FLIP_CAUSE_REVERSE_GAME,
    DementorState,
)
from game.proximity import BUCKET_ORDER, derive_proximity
from organize.models import DEMENTOR_EMPTY_DIE, UserProfile


def dementors_enabled(session):
    """Effective opt-in gate; everything in this module is inert without it."""
    return bool(session.effective('dementors_enabled'))


def assign_initial_roles(session, now=None):
    """Seed DementorState for every active roster member of `session`.

    `dementor_initial_dementors` randomly-chosen players start as
    DEMENTOR with 0 energy; everyone else starts as WIZARD with the
    effective starting energy. Idempotent: players who already have a
    state keep it (safe to re-run on a re-start).
    """
    now = now or timezone.now()
    profiles = list(
        UserProfile.objects
        .filter(
            memberships__team__session=session,
            memberships__is_active=True,
        )
        .distinct()
    )
    existing = set(
        DementorState.objects
        .filter(session=session)
        .values_list('player_id', flat=True)
    )
    fresh = [p for p in profiles if p.pk not in existing]
    if not fresh:
        return []

    starting_energy = session.effective('dementor_starting_energy')
    n_dementors = min(session.effective('dementor_initial_dementors'), len(fresh))
    # Only top up to the configured count if no dementor exists yet.
    already_dementors = DementorState.objects.filter(
        session=session, role=DementorState.DEMENTOR,
    ).count()
    n_dementors = max(0, n_dementors - already_dementors)
    chosen = set(random.sample(range(len(fresh)), n_dementors)) if n_dementors else set()

    states = []
    for index, profile in enumerate(fresh):
        is_dementor = index in chosen
        states.append(DementorState(
            session=session,
            player=profile,
            role=DementorState.DEMENTOR if is_dementor else DementorState.WIZARD,
            energy=0.0 if is_dementor else starting_energy,
            last_tick_at=now,
        ))
    return DementorState.objects.bulk_create(states)


def run_tick(session, now=None):
    """Derive proximity and (when the mode is on) apply the economy.

    Returns the derived ProximityEvents. This is the single tick entry
    point the report-ingestion endpoint calls.
    """
    now = now or timezone.now()
    events = derive_proximity(session, now=now)
    if dementors_enabled(session):
        economy_tick(session, events, now=now)
    return events


def _adjacency(session, events, state_player_ids):
    """player_id → set(player_id) within the effective drain-range bucket."""
    range_bucket = session.effective('dementor_drain_range_bucket')
    max_order = BUCKET_ORDER[range_bucket]
    near = {}
    for event in events:
        if BUCKET_ORDER.get(event.distance_bucket, 99) > max_order:
            continue
        a, b = event.player_a_id, event.player_b_id
        if a not in state_player_ids or b not in state_player_ids:
            continue
        near.setdefault(a, set()).add(b)
        near.setdefault(b, set()).add(a)
    return near


def economy_tick(session, events, now=None):
    """Apply one economy tick from the given ProximityEvents.

    Roles are evaluated as of the tick start, all deltas are computed,
    then flips resolve — so a flip never retroactively changes this
    tick's drains. Stale players (no fresh events) simply take no drain.
    """
    now = now or timezone.now()
    window_seconds = session.effective('ble_freshness_window_seconds')
    drain_rate = session.effective('dementor_drain_per_second')
    regen_rate = session.effective('dementor_wizard_regen_per_second')
    restore_rate = session.effective('dementor_restore_per_second')
    safety_in_numbers = session.effective('dementor_safety_in_numbers')
    group_size = session.effective('dementor_reverse_group_size')
    hold_seconds = session.effective('dementor_reverse_hold_seconds')
    threshold = session.effective('dementor_conversion_threshold')
    starting_energy = session.effective('dementor_starting_energy')
    empty_outcome = session.effective('dementor_empty_outcome')

    with transaction.atomic():
        states = list(
            DementorState.objects
            .select_for_update()
            .filter(session=session, alive=True)
        )
        by_player = {state.player_id: state for state in states}
        near = _adjacency(session, events, set(by_player))
        wizards = {pid for pid, s in by_player.items() if s.role == DementorState.WIZARD}
        dementors = {pid for pid, s in by_player.items() if s.role == DementorState.DEMENTOR}

        for state in states:
            elapsed = 0.0
            if state.last_tick_at is not None:
                elapsed = (now - state.last_tick_at).total_seconds()
            # Clamp: never negative, never longer than the freshness
            # window (a long gap means stale phones, not a mega-drain).
            elapsed = max(0.0, min(elapsed, float(window_seconds)))
            contacts = near.get(state.player_id, set())
            delta = 0.0

            if state.player_id in wizards:
                dementors_near = contacts & dementors
                if dementors_near:
                    rate = drain_rate
                    if safety_in_numbers:
                        cluster = len(contacts & wizards) + 1  # includes self
                        rate = drain_rate / cluster
                    delta = -rate * elapsed
                elif regen_rate:
                    delta = min(
                        regen_rate * elapsed,
                        max(0.0, starting_energy - state.energy),
                    )
                state.energy = max(0.0, state.energy + delta)
                state.hold_started_at = None
                if state.energy <= 0.0 and delta < 0.0:
                    if empty_outcome == DEMENTOR_EMPTY_DIE:
                        state.record_flip(DementorState.WIZARD, FLIP_CAUSE_DIED, when=now)
                    else:
                        state.record_flip(
                            DementorState.DEMENTOR, FLIP_CAUSE_DRAINED, when=now,
                        )
            else:
                wizards_near = contacts & wizards
                held = len(wizards_near) >= group_size
                if held:
                    delta = restore_rate * elapsed
                    state.energy += delta
                    if state.hold_started_at is None:
                        state.hold_started_at = now
                else:
                    # Group dropped below N: hold progress resets.
                    state.hold_started_at = None

                if (
                    held
                    and state.hold_started_at is not None
                    and (now - state.hold_started_at).total_seconds() >= hold_seconds
                ):
                    # Reverse numbers game: freed by the group — restart
                    # as a wizard with full energy.
                    state.record_flip(
                        DementorState.WIZARD, FLIP_CAUSE_REVERSE_GAME, when=now,
                    )
                    state.energy = starting_energy
                    state.hold_started_at = None
                elif state.energy >= threshold:
                    # Two-way conversion along the single energy axis.
                    state.record_flip(
                        DementorState.WIZARD, FLIP_CAUSE_CONVERSION, when=now,
                    )
                    state.hold_started_at = None

            state.last_delta = delta
            state.last_tick_at = now
            state.save(update_fields=[
                'role', 'energy', 'alive', 'last_delta', 'last_tick_at',
                'hold_started_at', 'updated_at',
            ])
    return states

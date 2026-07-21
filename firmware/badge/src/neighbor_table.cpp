#include "neighbor_table.h"

#include <string.h>

#include "config.h"

namespace geogame::badge {

void NeighborTable::Observe(const char* badge_id, int8_t rssi,
                            uint32_t counter, uint32_t now_ms) {
  Neighbor* free_slot = nullptr;
  Neighbor* stalest = nullptr;
  for (auto& slot : slots_) {
    if (slot.used && memcmp(slot.badge_id, badge_id, kBadgeIdLen) == 0) {
      // Known neighbor: keep the latest reading. No smoothing here on
      // purpose — the server owns RSSI smoothing and bucketing.
      slot.rssi = rssi;
      slot.counter = counter;
      slot.last_heard_ms = now_ms;
      return;
    }
    if (!slot.used && free_slot == nullptr) free_slot = &slot;
    if (slot.used &&
        (stalest == nullptr || slot.last_heard_ms < stalest->last_heard_ms)) {
      stalest = &slot;
    }
  }
  Neighbor* target = free_slot != nullptr ? free_slot : stalest;
  if (target == nullptr) return;  // table size 0 — can't happen
  memcpy(target->badge_id, badge_id, kBadgeIdLen);
  target->rssi = rssi;
  target->counter = counter;
  target->last_heard_ms = now_ms;
  target->used = true;
}

size_t NeighborTable::Drain(Observation* out, size_t max, uint32_t now_ms,
                            uint32_t ttl_ms) {
  size_t n = 0;
  for (auto& slot : slots_) {
    if (!slot.used) continue;
    if (now_ms - slot.last_heard_ms > ttl_ms) {
      slot.used = false;  // stale: silently dropped, never reported
      continue;
    }
    if (n < max) {
      memcpy(out[n].seen_badge_id, slot.badge_id, kBadgeIdLen);
      out[n].rssi = slot.rssi;
      out[n].counter = slot.counter;
      slot.used = false;
      ++n;
    }
    // Entries beyond `max` stay for the next flush.
  }
  return n;
}

size_t NeighborTable::FreshCount(uint32_t now_ms, uint32_t ttl_ms) const {
  size_t n = 0;
  for (const auto& slot : slots_) {
    if (slot.used && now_ms - slot.last_heard_ms <= ttl_ms) ++n;
  }
  return n;
}

}  // namespace geogame::badge

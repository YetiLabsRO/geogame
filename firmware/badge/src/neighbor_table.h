// Fixed-size table of recently heard badge beacons.
//
// The badge is a passive sensor: it logs (badge_id, RSSI, counter) for
// every beacon it hears and periodically flushes the table toward any
// gateway in range. It never decides what proximity *means* — the
// server maps RSSI to range buckets (wearable-badge spec).
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "protocol.h"

namespace geogame::badge {

struct Neighbor {
  char badge_id[kBadgeIdLen];
  int8_t rssi;          // latest reading, dBm
  uint32_t counter;     // latest beacon counter heard
  uint32_t last_heard_ms;
  bool used;
};

class NeighborTable {
 public:
  // Record a heard beacon; updates in place or evicts the stalest slot.
  void Observe(const char* badge_id, int8_t rssi, uint32_t counter,
               uint32_t now_ms);

  // Copy up to `max` fresh (within ttl) entries into `out`, then clear
  // the table so each observation is reported at most once per flush.
  size_t Drain(Observation* out, size_t max, uint32_t now_ms, uint32_t ttl_ms);

  size_t FreshCount(uint32_t now_ms, uint32_t ttl_ms) const;

 private:
  Neighbor slots_[kNeighborTableSize] = {};
};

}  // namespace geogame::badge

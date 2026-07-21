// HTTP uplink to POST /api/gateway/ingest/ with batching + backoff.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "espnow_collector.h"
#include "protocol.h"

namespace geogame::gateway {

class Uplink {
 public:
  bool Begin();
  bool Connected();

  // POST one batch. On success, fills `downlinks` (up to `max`) from
  // the response's badge_states and returns the count via
  // *downlink_count; returns false on any transport/HTTP failure (the
  // caller keeps its reports and retries after Backoff()).
  bool PostBatch(const CollectedReport* reports, size_t report_count,
                 geogame::DownlinkPacket* downlinks, size_t max,
                 size_t* downlink_count);

  // Current backoff delay; doubles per consecutive failure, resets on
  // success (kBackoffInitialMs .. kBackoffMaxMs).
  uint32_t BackoffMs() const { return backoff_ms_; }

 private:
  uint32_t backoff_ms_ = 0;
};

}  // namespace geogame::gateway

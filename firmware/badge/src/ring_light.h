// RGB ring state machine: a pure display of server-authored state.
//
// The ring renders the last DownlinkPacket verbatim (energy fill in the
// role color). When the downlink goes quiet past kDownlinkStaleMs the
// badge does NOT invent new state — it keeps the last-known frame and
// overlays a distinct stale/disconnected blink (wearable-badge spec).
#pragma once

#include <stdint.h>

#include "protocol.h"

namespace geogame::badge {

class RingLight {
 public:
  void Begin();

  // Adopt fresh server state from a downlink addressed to this badge.
  void ApplyDownlink(const DownlinkPacket& state, uint32_t now_ms);

  // Render one frame; call from the main loop (handles stale overlay,
  // low-battery indication and blink phases from now_ms).
  void Render(uint32_t now_ms, bool low_battery);

 private:
  DownlinkPacket last_state_ = {};
  bool has_state_ = false;
  uint32_t last_downlink_ms_ = 0;
};

}  // namespace geogame::badge

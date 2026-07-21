// ESP-NOW side of the gateway: collect badge ReportPackets, broadcast
// DownlinkPackets.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "protocol.h"

namespace geogame::gateway {

// One collected report, ready for JSON serialization.
struct CollectedReport {
  geogame::ReportPacket report;
  uint32_t received_ms;
};

class EspNowCollector {
 public:
  // Init ESP-NOW alongside the WiFi station (shared radio/channel) and
  // start collecting ReportPackets into the ring buffer.
  bool Begin();

  // Move up to `max` buffered reports into `out`; returns the count.
  size_t Drain(CollectedReport* out, size_t max);

  // Broadcast one server-authored per-badge state onto the mesh.
  void SendDownlink(const geogame::DownlinkPacket& packet);

  size_t dropped() const { return dropped_; }

 private:
  size_t dropped_ = 0;
};

}  // namespace geogame::gateway

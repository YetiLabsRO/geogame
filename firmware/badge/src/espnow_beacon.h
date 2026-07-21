// ESP-NOW peer discovery: broadcast our beacon, log every beacon heard.
//
// Connectionless by design — no pairing, no router, no phone in the
// loop. Everything goes to the broadcast address; the shared recv
// callback filters by magic/version and feeds the neighbor table.
#pragma once

#include <stdint.h>

#include "neighbor_table.h"
#include "protocol.h"

namespace geogame::badge {

class EspNowBeacon {
 public:
  // Init WiFi STA (no AP association), esp_now, LR mode if configured,
  // and register the broadcast peer + recv callback.
  bool Begin(const char* badge_id, NeighborTable* table);

  // Broadcast one BeaconPacket with the next rolling counter.
  void SendBeacon(bool low_battery);

  // Send a ReportPacket (observations + telemetry) to the broadcast
  // address; any gateway in range picks it up. Returns false when the
  // TX queue rejects the packet (caller keeps the buffer for retry).
  bool SendReport(const ReportPacket& report);

  // Latest DownlinkPacket addressed to this badge (returns false if
  // none arrived since the last call).
  bool TakeDownlink(DownlinkPacket* out);

  uint32_t counter() const { return counter_; }

 private:
  static void OnReceive(const uint8_t* mac, const uint8_t* data, int len);

  char badge_id_[kBadgeIdLen] = {};
  // Rolling beacon counter. TODO(power): persist in RTC slow memory so
  // deep-sleep cycles do not reset it (the server dedupes on it).
  uint32_t counter_ = 0;
  NeighborTable* table_ = nullptr;
};

}  // namespace geogame::badge

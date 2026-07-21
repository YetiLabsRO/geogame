// Provisioning: give the badge its opaque on-air id (and options)
// before hand-out.
//
// Flow: staff register the badge in the backend (POST /api/staff/badges/
// returns the badge_id), then write that id into the badge over the USB
// serial console:
//
//     PROV id=aa110001
//     PROV show
//
// The id persists in NVS. A BLE provisioning channel (write the id via
// a GATT characteristic instead of a cable) is stubbed for later —
// serial is sufficient for a hand-assembled pilot fleet.
#pragma once

#include "protocol.h"

namespace geogame::badge {

class Provisioning {
 public:
  // Load the stored badge id; false when the badge is blank (stay in
  // provisioning mode and blink the ring until an id is written).
  bool Load(char out_badge_id[kBadgeIdLen]);

  // Poll the serial console for PROV commands; call from loop().
  void PollSerial();

  // TODO(ble): optional GATT provisioning service (write-only id
  // characteristic, protected by a provisioning window at boot). BLE
  // and ESP-NOW share the single C3 radio — keep the service torn down
  // during play so it never competes with detection airtime.
  void BeginBleStub() {}
};

}  // namespace geogame::badge

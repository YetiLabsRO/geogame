// Gateway relay configuration (wearable-badge-hardware).
//
// A gateway is a thin relay: it skims ReportPackets off the ESP-NOW
// field, batches them, POSTs to the backend, and re-broadcasts the
// per-badge state from the response. It holds a PER-GATEWAY credential
// — never a player token.
#pragma once

#include <stdint.h>

namespace geogame::gateway {

// --- Uplink ----------------------------------------------------------------
// TODO(deploy): per-site values; consider NVS + a serial provisioning
// console like the badge's instead of compile-time constants.
constexpr char kWifiSsid[] = "CHANGE_ME";
constexpr char kWifiPassword[] = "CHANGE_ME";
constexpr char kIngestUrl[] = "https://example.invalid/api/gateway/ingest/";
// From POST /api/staff/gateways/ (staff fleet panel shows it).
constexpr char kGatewayToken[] = "CHANGE_ME";

// Batch flush cadence + capacity. Reports accumulate between flushes;
// when offline the buffer keeps the newest kMaxBufferedReports.
constexpr uint32_t kFlushIntervalMs = 3000;
constexpr size_t kMaxBufferedReports = 64;

// Exponential backoff for a failing uplink.
constexpr uint32_t kBackoffInitialMs = 2000;
constexpr uint32_t kBackoffMaxMs = 60 * 1000;

// --- Mesh ------------------------------------------------------------------
// ESP-NOW and the WiFi uplink share one radio: the station channel is
// whatever the AP dictates, and every badge must beacon on that same
// channel. Fix the AP channel at the venue (or use a 4G/tablet uplink)
// — channel drift between badges and gateways is the #1 silent-failure
// mode of this topology.
constexpr uint8_t kEspNowChannel = 1;

// Must match the badge fleet (see badge/include/config.h): LR mode is
// all-or-nothing across the deployment.
constexpr bool kLongRangeMode = false;

// How many badge_states from one ingest response we re-broadcast per
// flush; kept modest to bound airtime.
constexpr size_t kMaxDownlinksPerFlush = 64;

}  // namespace geogame::gateway

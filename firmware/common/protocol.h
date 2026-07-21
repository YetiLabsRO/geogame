// Wire protocol shared by badge + gateway firmware and mirrored by the
// backend (game/badges.py GATEWAY_PROTOCOL_VERSION). Version every
// breaking change; the ingest endpoint refuses mismatched versions so
// stale firmware fails loudly instead of half-working.
//
// Two transports meet here:
//   * ESP-NOW packets on the 2.4 GHz mesh (badge<->badge, badge<->gateway)
//   * HTTP JSON between gateway and POST /api/gateway/ingest/
//
// ESP-NOW payloads are capped at 250 bytes — every struct below must
// stay well under that (static_asserts enforce it).
#pragma once

#include <stdint.h>

namespace geogame {

// Bump together with the backend's GATEWAY_PROTOCOL_VERSION.
constexpr uint8_t kProtocolVersion = 1;

// First bytes of every ESP-NOW payload so foreign traffic on the
// broadcast address is cheap to reject.
constexpr uint16_t kMagic = 0xC3A7;

// Opaque on-air badge id: 8 hex chars, assigned at provisioning by the
// backend registry (BadgeDevice.badge_id). Not NUL-terminated on air.
constexpr size_t kBadgeIdLen = 8;

enum class PacketType : uint8_t {
  kBeacon = 1,     // badge -> everyone: "I exist", rolling counter
  kReport = 2,     // badge -> gateways: buffered observations + telemetry
  kDownlink = 3,   // gateway -> badges: server-authored display state
};

// ---------------------------------------------------------------------------
// Beacon: broadcast every kBeaconIntervalMs. Peers log (badge_id, RSSI,
// counter); the counter is what lets the server dedupe an observation
// relayed by two gateways.
// ---------------------------------------------------------------------------
struct __attribute__((packed)) BeaconPacket {
  uint16_t magic = kMagic;
  uint8_t version = kProtocolVersion;
  uint8_t type = static_cast<uint8_t>(PacketType::kBeacon);
  char badge_id[kBadgeIdLen];
  uint32_t counter;  // rolling, persisted across deep sleep in RTC memory
  uint8_t flags;     // bit0: low battery, bit1: LR mode active
};
static_assert(sizeof(BeaconPacket) <= 32, "beacon must stay tiny");

// One neighbor observation as buffered on the badge.
struct __attribute__((packed)) Observation {
  char seen_badge_id[kBadgeIdLen];
  int8_t rssi;       // dBm as reported by esp_now recv_info
  uint32_t counter;  // the *seen* badge's beacon counter
};

// IMU activity classes — mirrored by BadgeTelemetry.activity.
enum class Activity : uint8_t {
  kUnknown = 0,
  kStill = 1,
  kStanding = 2,
  kRunning = 3,
};

// IMU gesture events — mirrored by BadgeTelemetry.gesture.
enum class Gesture : uint8_t {
  kNone = 0,
  kCast = 1,
  kDrain = 2,
};

// ---------------------------------------------------------------------------
// Report: a badge's buffered observations + telemetry, flushed toward
// any gateway in range every kReportIntervalMs. Badges never route each
// other's reports (no multi-hop) — a report either reaches a gateway or
// waits in the ring buffer for the next flush.
// ---------------------------------------------------------------------------
constexpr size_t kMaxObservationsPerReport = 12;  // keeps packet < 250 B

struct __attribute__((packed)) ReportPacket {
  uint16_t magic = kMagic;
  uint8_t version = kProtocolVersion;
  uint8_t type = static_cast<uint8_t>(PacketType::kReport);
  char badge_id[kBadgeIdLen];
  uint8_t battery_pct;      // 0..100, 0xFF = unknown
  uint8_t activity;         // Activity
  uint8_t gesture;          // Gesture since last report (kNone if none)
  uint8_t observation_count;
  char firmware_version[8]; // e.g. "0.1.0", NUL-padded
  Observation observations[kMaxObservationsPerReport];
};
static_assert(sizeof(ReportPacket) <= 250, "ESP-NOW payload cap");

// ---------------------------------------------------------------------------
// Downlink: server-authored display state, re-broadcast by gateways.
// Badges apply only the packet addressed to their own badge_id. The
// ring renders exactly this — the badge invents nothing.
// ---------------------------------------------------------------------------
enum class RingPattern : uint8_t {
  kIdle = 0,        // no game state (unassigned / mode off)
  kEnergyFill = 1,  // fill_pct of the ring lit in role color
  kOut = 2,         // out of play
  // kStale is NOT sent by the server: the badge overlays it locally
  // when the downlink goes quiet longer than kDownlinkStaleMs.
};

enum class RingColor : uint8_t {
  kNone = 0,
  kWarm = 1,  // wizard
  kCold = 2,  // dementor
};

struct __attribute__((packed)) DownlinkPacket {
  uint16_t magic = kMagic;
  uint8_t version = kProtocolVersion;
  uint8_t type = static_cast<uint8_t>(PacketType::kDownlink);
  char badge_id[kBadgeIdLen];  // addressee
  uint8_t pattern;             // RingPattern
  uint8_t fill_pct;            // 0..100
  uint8_t color;               // RingColor
  uint8_t flags;               // reserved (active effects)
};
static_assert(sizeof(DownlinkPacket) <= 32, "downlink must stay tiny");

}  // namespace geogame

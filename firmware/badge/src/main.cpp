// Wearable badge firmware — main loop (wearable-badge-hardware).
//
// The badge is an always-on proximity sensor + a glanceable light:
//   * broadcast an ESP-NOW beacon (opaque id + rolling counter),
//   * log every beacon heard (id + RSSI) into the neighbor table,
//   * flush observations + telemetry toward gateways every report
//     interval,
//   * render the last server-authored ring state (energy/role), with a
//     local stale overlay when the downlink goes quiet.
//
// It never decides game outcomes: no drain logic, no role logic, no
// range thresholds live here (wearable-badge spec).
#include <Arduino.h>
#include <string.h>

#include "battery.h"
#include "config.h"
#include "espnow_beacon.h"
#include "imu.h"
#include "neighbor_table.h"
#include "protocol.h"
#include "provisioning.h"
#include "ring_light.h"

using namespace geogame;
using namespace geogame::badge;

namespace {

NeighborTable g_table;
EspNowBeacon g_radio;
RingLight g_ring;
Imu g_imu;
Battery g_battery;
Provisioning g_provisioning;

char g_badge_id[kBadgeIdLen];
bool g_provisioned = false;

uint32_t g_last_beacon_ms = 0;
uint32_t g_last_report_ms = 0;
uint32_t g_last_imu_ms = 0;

// One report buffer, kept until a send succeeds so a gateway coverage
// gap only delays (never silently drops) buffered observations.
ReportPacket g_report;
bool g_report_pending = false;

void BuildReport(uint32_t now_ms) {
  memset(&g_report, 0, sizeof(g_report));
  g_report.magic = kMagic;
  g_report.version = kProtocolVersion;
  g_report.type = static_cast<uint8_t>(PacketType::kReport);
  memcpy(g_report.badge_id, g_badge_id, kBadgeIdLen);
  g_report.battery_pct = g_battery.Percent();
  g_report.activity = static_cast<uint8_t>(g_imu.CurrentActivity());
  g_report.gesture = static_cast<uint8_t>(g_imu.TakeGesture());
  strncpy(g_report.firmware_version, kFirmwareVersion,
          sizeof(g_report.firmware_version) - 1);
  g_report.observation_count = static_cast<uint8_t>(g_table.Drain(
      g_report.observations, kMaxObservationsPerReport, now_ms,
      kNeighborTtlMs));
  // TODO(pilot): fold dead-reckoning (g_imu.TakeDeadReckoning()) into
  // the report once the packet has room budgeted for it; the backend
  // telemetry path already accepts an `imu` payload for it.
}

}  // namespace

void setup() {
  Serial.begin(115200);
  g_provisioned = g_provisioning.Load(g_badge_id);
  g_ring.Begin();
  g_battery.Begin();
  g_imu.Begin();
  if (g_provisioned) {
    if (!g_radio.Begin(g_badge_id, &g_table)) {
      Serial.println("FATAL: esp_now init failed");
    }
    Serial.printf("badge %.*s up, fw %s\n", static_cast<int>(kBadgeIdLen),
                  g_badge_id, kFirmwareVersion);
  } else {
    Serial.println("UNPROVISIONED — send: PROV id=<badge_id from backend>");
  }
}

void loop() {
  const uint32_t now_ms = millis();
  g_provisioning.PollSerial();

  if (!g_provisioned) {
    // Blink idle until provisioned; reboot applies a written id.
    g_ring.Render(now_ms, false);
    delay(50);
    return;
  }

  if (now_ms - g_last_imu_ms >= 1000 / kImuSampleHz) {
    g_last_imu_ms = now_ms;
    g_imu.Sample(now_ms);
  }

  if (now_ms - g_last_beacon_ms >= kBeaconIntervalMs) {
    g_last_beacon_ms = now_ms;
    g_radio.SendBeacon(g_battery.IsLow());
  }

  if (!g_report_pending && now_ms - g_last_report_ms >= kReportIntervalMs) {
    g_last_report_ms = now_ms;
    BuildReport(now_ms);
    g_report_pending = true;
  }
  if (g_report_pending) {
    // Opportunistic flush: retry each pass until the TX queue accepts.
    // ESP-NOW broadcast has no delivery ACK from gateways — coverage
    // overlap + server-side dedupe is the reliability story.
    if (g_radio.SendReport(g_report)) g_report_pending = false;
  }

  DownlinkPacket downlink;
  if (g_radio.TakeDownlink(&downlink)) {
    g_ring.ApplyDownlink(downlink, now_ms);
  }
  g_ring.Render(now_ms, g_battery.IsLow());

  // TODO(power): replace delay with modem-sleep duty cycling per
  // kScanDutyCyclePercent; measure advertise+scan+ring draw and tune
  // for a full multi-hour event on the ~500 mAh cell.
  delay(10);
}

// Badge firmware configuration (wearable-badge-hardware).
//
// Cadence values mirror the server's Session-effective BLE substrate
// knobs (ble_report_interval_seconds etc.); the server remains the
// tuning authority — treat these as power-on defaults that a future
// provisioning push may override.
#pragma once

#include <stdint.h>

namespace geogame::badge {

// --- Radio -----------------------------------------------------------------
// Beacon cadence. ESP-NOW broadcast is cheap; 1 Hz keeps neighbor
// tables fresh at walking speed while leaving room for duty cycling.
constexpr uint32_t kBeaconIntervalMs = 1000;

// Observation flush toward gateways. Matches the server default
// ble_report_interval_seconds (10 s).
constexpr uint32_t kReportIntervalMs = 10 * 1000;

// Radio duty cycle: fraction of each beacon interval the receiver is
// actually listening. TODO(power): measure real draw before tuning —
// modem-sleep between slots is the main battery lever.
constexpr uint8_t kScanDutyCyclePercent = 100;

// ESP-NOW Long-Range mode (esp_wifi_set_protocol(..., WIFI_PROTOCOL_LR)):
// extends range well beyond the default tens-of-meters at reduced
// throughput. Per-deployment choice; both sides of a link must agree,
// so flip it fleet-wide (badges AND gateways) or not at all.
constexpr bool kLongRangeMode = false;

// --- Neighbor table --------------------------------------------------------
constexpr size_t kNeighborTableSize = 32;
// Drop neighbors not heard for this long (stale entries never reach a
// report — absence of observation, never fabricated proximity).
constexpr uint32_t kNeighborTtlMs = 15 * 1000;

// --- Ring light ------------------------------------------------------------
constexpr uint8_t kRingLedPin = 8;   // TODO(pcb): final GPIO per layout
constexpr uint8_t kRingLedCount = 12;
constexpr uint8_t kRingBrightness = 64;  // of 255; battery vs readability
// Overlay the stale/disconnected pattern when no downlink arrived for
// this long. The last-known state keeps rendering underneath.
constexpr uint32_t kDownlinkStaleMs = 30 * 1000;

// --- IMU -------------------------------------------------------------------
constexpr uint8_t kImuSdaPin = 4;    // TODO(pcb): final I2C pins
constexpr uint8_t kImuSclPin = 5;
constexpr uint32_t kImuSampleHz = 50;

// --- Battery ---------------------------------------------------------------
constexpr uint8_t kBatteryAdcPin = 2;  // TODO(pcb): divider on VBAT
// TODO(hardware): calibrate against the real divider + LiPo curve.
constexpr float kBatteryDividerRatio = 2.0f;
constexpr float kBatteryFullVolts = 4.2f;
constexpr float kBatteryEmptyVolts = 3.3f;
constexpr uint8_t kLowBatteryPct = 20;

constexpr char kFirmwareVersion[] = "0.1.0";

}  // namespace geogame::badge

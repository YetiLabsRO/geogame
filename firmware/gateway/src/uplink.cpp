#include "uplink.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <string.h>

#include "config.h"

namespace geogame::gateway {
namespace {

const char* ActivityName(uint8_t activity) {
  switch (static_cast<geogame::Activity>(activity)) {
    case geogame::Activity::kStill:
      return "STILL";
    case geogame::Activity::kStanding:
      return "STANDING";
    case geogame::Activity::kRunning:
      return "RUNNING";
    default:
      return nullptr;
  }
}

const char* GestureName(uint8_t gesture) {
  switch (static_cast<geogame::Gesture>(gesture)) {
    case geogame::Gesture::kCast:
      return "CAST";
    case geogame::Gesture::kDrain:
      return "DRAIN";
    default:
      return nullptr;
  }
}

geogame::DownlinkPacket ToDownlink(JsonObjectConst state) {
  geogame::DownlinkPacket packet;
  packet.magic = geogame::kMagic;
  packet.version = geogame::kProtocolVersion;
  packet.type = static_cast<uint8_t>(geogame::PacketType::kDownlink);
  const char* badge_id = state["badge_id"] | "";
  strncpy(packet.badge_id, badge_id, geogame::kBadgeIdLen);
  JsonObjectConst ring = state["ring"];
  const char* pattern = ring["pattern"] | "IDLE";
  if (strcmp(pattern, "ENERGY_FILL") == 0) {
    packet.pattern = static_cast<uint8_t>(geogame::RingPattern::kEnergyFill);
  } else if (strcmp(pattern, "OUT") == 0) {
    packet.pattern = static_cast<uint8_t>(geogame::RingPattern::kOut);
  } else {
    packet.pattern = static_cast<uint8_t>(geogame::RingPattern::kIdle);
  }
  packet.fill_pct = ring["fill_pct"] | 0;
  const char* color = ring["color"] | "";
  if (strcmp(color, "WARM") == 0) {
    packet.color = static_cast<uint8_t>(geogame::RingColor::kWarm);
  } else if (strcmp(color, "COLD") == 0) {
    packet.color = static_cast<uint8_t>(geogame::RingColor::kCold);
  } else {
    packet.color = static_cast<uint8_t>(geogame::RingColor::kNone);
  }
  packet.flags = 0;
  return packet;
}

}  // namespace

bool Uplink::Begin() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(kWifiSsid, kWifiPassword);
  // Non-blocking: Connected() gates the flush loop.
  return true;
}

bool Uplink::Connected() { return WiFi.status() == WL_CONNECTED; }

bool Uplink::PostBatch(const CollectedReport* reports, size_t report_count,
                       geogame::DownlinkPacket* downlinks, size_t max,
                       size_t* downlink_count) {
  *downlink_count = 0;
  if (!Connected()) {
    backoff_ms_ = backoff_ms_ == 0
                      ? kBackoffInitialMs
                      : min(backoff_ms_ * 2, kBackoffMaxMs);
    return false;
  }

  // Build the versioned ingest payload (see openspec design.md and
  // game/badges.py: observations use the SEEN badge's beacon counter so
  // the server can dedupe overlapping gateway coverage).
  JsonDocument doc;
  doc["protocol_version"] = geogame::kProtocolVersion;
  JsonArray observations = doc["observations"].to<JsonArray>();
  JsonArray telemetry = doc["telemetry"].to<JsonArray>();
  for (size_t i = 0; i < report_count; ++i) {
    const geogame::ReportPacket& report = reports[i].report;
    char badge_id[geogame::kBadgeIdLen + 1] = {};
    memcpy(badge_id, report.badge_id, geogame::kBadgeIdLen);

    for (uint8_t j = 0; j < report.observation_count &&
                        j < geogame::kMaxObservationsPerReport;
         ++j) {
      const geogame::Observation& obs = report.observations[j];
      char seen_id[geogame::kBadgeIdLen + 1] = {};
      memcpy(seen_id, obs.seen_badge_id, geogame::kBadgeIdLen);
      JsonObject entry = observations.add<JsonObject>();
      entry["badge_id"] = badge_id;
      entry["seen_badge_id"] = seen_id;
      entry["rssi"] = obs.rssi;
      entry["counter"] = obs.counter;
    }

    JsonObject sample = telemetry.add<JsonObject>();
    sample["badge_id"] = badge_id;
    if (report.battery_pct <= 100) sample["battery_pct"] = report.battery_pct;
    if (const char* activity = ActivityName(report.activity)) {
      sample["activity"] = activity;
    }
    if (const char* gesture = GestureName(report.gesture)) {
      sample["gesture"] = gesture;
    }
    char firmware[sizeof(report.firmware_version) + 1] = {};
    memcpy(firmware, report.firmware_version, sizeof(report.firmware_version));
    if (firmware[0] != '\0') sample["firmware_version"] = firmware;
  }

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  // TODO(deploy): pin the server TLS cert (or at least the CA) instead
  // of the default insecure client when kIngestUrl is https.
  http.begin(kIngestUrl);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Gateway-Token", kGatewayToken);
  const int status = http.POST(body);
  if (status != 200) {
    http.end();
    backoff_ms_ = backoff_ms_ == 0
                      ? kBackoffInitialMs
                      : min(backoff_ms_ * 2, kBackoffMaxMs);
    return false;
  }

  JsonDocument response;
  const DeserializationError err = deserializeJson(response, http.getString());
  http.end();
  backoff_ms_ = 0;
  if (err) return true;  // ingest succeeded; downlink just skipped

  for (JsonObjectConst state :
       response["badge_states"].as<JsonArrayConst>()) {
    if (*downlink_count >= max) break;
    downlinks[(*downlink_count)++] = ToDownlink(state);
  }
  return true;
}

}  // namespace geogame::gateway

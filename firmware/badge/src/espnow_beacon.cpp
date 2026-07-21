#include "espnow_beacon.h"

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <string.h>

#include "config.h"

namespace geogame::badge {
namespace {

constexpr uint8_t kBroadcastMac[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// esp_now callbacks are C-style; route through a singleton.
EspNowBeacon* g_instance = nullptr;
DownlinkPacket g_pending_downlink;
volatile bool g_has_downlink = false;

}  // namespace

bool EspNowBeacon::Begin(const char* badge_id, NeighborTable* table) {
  memcpy(badge_id_, badge_id, kBadgeIdLen);
  table_ = table;
  g_instance = this;

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();  // ESP-NOW only; no AP association on the badge
  if (kLongRangeMode) {
    // LR is a link-level protocol switch: EVERY node in the deployment
    // (badges and gateways) must enable it or they go mutually deaf.
    esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_LR);
  }

  if (esp_now_init() != ESP_OK) return false;

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, kBroadcastMac, sizeof(kBroadcastMac));
  peer.channel = 0;  // current channel
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) return false;

  // Arduino-ESP32 v3 signature (esp_now_recv_info_t carries RSSI).
  esp_now_register_recv_cb([](const esp_now_recv_info_t* info,
                              const uint8_t* data, int len) {
    if (g_instance == nullptr || len < 4) return;
    // TODO(radio): rx_ctrl->rssi is the per-packet RSSI we report;
    // verify field availability on the pinned IDF version.
    int8_t rssi = info->rx_ctrl != nullptr
                      ? static_cast<int8_t>(info->rx_ctrl->rssi)
                      : -127;
    const uint16_t magic = static_cast<uint16_t>(data[0]) |
                           (static_cast<uint16_t>(data[1]) << 8);
    if (magic != kMagic || data[2] != kProtocolVersion) return;

    switch (static_cast<PacketType>(data[3])) {
      case PacketType::kBeacon: {
        if (len < static_cast<int>(sizeof(BeaconPacket))) return;
        BeaconPacket beacon;
        memcpy(&beacon, data, sizeof(beacon));
        if (memcmp(beacon.badge_id, g_instance->badge_id_, kBadgeIdLen) == 0)
          return;  // our own echo
        g_instance->table_->Observe(beacon.badge_id, rssi, beacon.counter,
                                    millis());
        break;
      }
      case PacketType::kDownlink: {
        if (len < static_cast<int>(sizeof(DownlinkPacket))) return;
        DownlinkPacket downlink;
        memcpy(&downlink, data, sizeof(downlink));
        // Apply only the state addressed to us.
        if (memcmp(downlink.badge_id, g_instance->badge_id_, kBadgeIdLen) != 0)
          return;
        g_pending_downlink = downlink;
        g_has_downlink = true;
        break;
      }
      default:
        break;  // reports are gateway-bound; badges ignore them
    }
  });
  return true;
}

void EspNowBeacon::SendBeacon(bool low_battery) {
  BeaconPacket beacon;
  memcpy(beacon.badge_id, badge_id_, kBadgeIdLen);
  beacon.counter = ++counter_;
  beacon.flags = (low_battery ? 0x01 : 0x00) | (kLongRangeMode ? 0x02 : 0x00);
  esp_now_send(kBroadcastMac, reinterpret_cast<const uint8_t*>(&beacon),
               sizeof(beacon));
}

bool EspNowBeacon::SendReport(const ReportPacket& report) {
  // Trim to the used observation slots to keep airtime down.
  const size_t used =
      sizeof(ReportPacket) -
      (kMaxObservationsPerReport - report.observation_count) *
          sizeof(Observation);
  return esp_now_send(kBroadcastMac,
                      reinterpret_cast<const uint8_t*>(&report),
                      used) == ESP_OK;
}

bool EspNowBeacon::TakeDownlink(DownlinkPacket* out) {
  if (!g_has_downlink) return false;
  *out = g_pending_downlink;
  g_has_downlink = false;
  return true;
}

}  // namespace geogame::badge

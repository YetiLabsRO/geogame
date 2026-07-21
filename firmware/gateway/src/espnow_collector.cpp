#include "espnow_collector.h"

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <string.h>

#include "config.h"

namespace geogame::gateway {
namespace {

constexpr uint8_t kBroadcastMac[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Simple ring buffer filled from the recv callback, drained from loop.
// The callback runs on the WiFi task — keep it allocation-free.
CollectedReport g_buffer[kMaxBufferedReports];
volatile size_t g_head = 0;
volatile size_t g_count = 0;
size_t g_dropped = 0;

void OnReceive(const esp_now_recv_info_t* info, const uint8_t* data,
               int len) {
  (void)info;
  if (len < 4) return;
  const uint16_t magic = static_cast<uint16_t>(data[0]) |
                         (static_cast<uint16_t>(data[1]) << 8);
  if (magic != geogame::kMagic || data[2] != geogame::kProtocolVersion) return;
  if (static_cast<geogame::PacketType>(data[3]) !=
      geogame::PacketType::kReport) {
    return;  // beacons are badge-to-badge; the gateway relays reports
  }
  if (g_count >= kMaxBufferedReports) {
    // Offline too long: drop the OLDEST so the freshest survives.
    g_head = (g_head + 1) % kMaxBufferedReports;
    g_count = g_count - 1;
    ++g_dropped;
  }
  const size_t slot = (g_head + g_count) % kMaxBufferedReports;
  memset(&g_buffer[slot].report, 0, sizeof(g_buffer[slot].report));
  memcpy(&g_buffer[slot].report, data,
         len < static_cast<int>(sizeof(geogame::ReportPacket))
             ? len
             : static_cast<int>(sizeof(geogame::ReportPacket)));
  g_buffer[slot].received_ms = millis();
  g_count = g_count + 1;
}

}  // namespace

bool EspNowCollector::Begin() {
  // WiFi.begin() was already called by the uplink; ESP-NOW shares the
  // station interface and therefore the AP's channel — see config.h on
  // why the AP channel must be pinned at the venue.
  if (kLongRangeMode) {
    esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_LR);
  }
  if (esp_now_init() != ESP_OK) return false;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, kBroadcastMac, sizeof(kBroadcastMac));
  peer.channel = 0;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) return false;
  esp_now_register_recv_cb(OnReceive);
  return true;
}

size_t EspNowCollector::Drain(CollectedReport* out, size_t max) {
  size_t n = 0;
  // NOTE: single-consumer; brief races with the producer only cost one
  // report until the next flush. TODO(robustness): portMUX critical
  // section if pilot logs ever show corruption here.
  while (g_count > 0 && n < max) {
    out[n++] = g_buffer[g_head];
    g_head = (g_head + 1) % kMaxBufferedReports;
    g_count = g_count - 1;
  }
  dropped_ = g_dropped;
  return n;
}

void EspNowCollector::SendDownlink(const geogame::DownlinkPacket& packet) {
  esp_now_send(kBroadcastMac, reinterpret_cast<const uint8_t*>(&packet),
               sizeof(packet));
}

}  // namespace geogame::gateway

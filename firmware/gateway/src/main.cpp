// Gateway relay firmware — main loop (wearable-badge-hardware).
//
// Thin by design (the server owns all game logic):
//   1. collect badge ReportPackets off the ESP-NOW field,
//   2. batch + POST them to /api/gateway/ingest/ (per-gateway token),
//      buffering with exponential backoff while the uplink is down,
//   3. re-broadcast the response's per-badge display state onto the
//      mesh for badges to render.
#include <Arduino.h>

#include "config.h"
#include "espnow_collector.h"
#include "protocol.h"
#include "uplink.h"

using namespace geogame;
using namespace geogame::gateway;

namespace {

EspNowCollector g_collector;
Uplink g_uplink;

CollectedReport g_batch[kMaxBufferedReports];
size_t g_batch_count = 0;

DownlinkPacket g_downlinks[kMaxDownlinksPerFlush];

uint32_t g_next_flush_ms = 0;

}  // namespace

void setup() {
  Serial.begin(115200);
  g_uplink.Begin();  // WiFi first: ESP-NOW shares the station channel
  if (!g_collector.Begin()) {
    Serial.println("FATAL: esp_now init failed");
  }
  Serial.println("gateway up");
}

void loop() {
  const uint32_t now_ms = millis();

  // Top up the local batch from the mesh ring buffer. Reports survive
  // failed flushes: g_batch is only cleared on a successful POST.
  g_batch_count += g_collector.Drain(g_batch + g_batch_count,
                                     kMaxBufferedReports - g_batch_count);

  if (now_ms >= g_next_flush_ms) {
    size_t downlink_count = 0;
    // Flush even when empty: the response still carries every active
    // badge's display state, which keeps rings fresh (and doubles as a
    // gateway heartbeat for the staff health row).
    if (g_uplink.PostBatch(g_batch, g_batch_count, g_downlinks,
                           kMaxDownlinksPerFlush, &downlink_count)) {
      g_batch_count = 0;
      for (size_t i = 0; i < downlink_count; ++i) {
        g_collector.SendDownlink(g_downlinks[i]);
        // Small gap so the burst doesn't monopolize airtime.
        delay(5);
      }
      g_next_flush_ms = now_ms + kFlushIntervalMs;
    } else {
      // Offline: back off, keep collecting. The mesh ring buffer drops
      // oldest-first if we stay dark past kMaxBufferedReports.
      g_next_flush_ms = now_ms + g_uplink.BackoffMs();
      Serial.printf("uplink failed, backoff %lu ms (%u buffered, %u dropped)\n",
                    static_cast<unsigned long>(g_uplink.BackoffMs()),
                    static_cast<unsigned>(g_batch_count),
                    static_cast<unsigned>(g_collector.dropped()));
    }
  }

  delay(20);
}

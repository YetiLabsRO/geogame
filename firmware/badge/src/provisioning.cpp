#include "provisioning.h"

#include <Arduino.h>
#include <Preferences.h>
#include <string.h>

namespace geogame::badge {
namespace {

constexpr char kNvsNamespace[] = "geogame";
constexpr char kNvsKeyBadgeId[] = "badge_id";

}  // namespace

bool Provisioning::Load(char out_badge_id[kBadgeIdLen]) {
  Preferences prefs;
  prefs.begin(kNvsNamespace, /*readOnly=*/true);
  const String stored = prefs.getString(kNvsKeyBadgeId, "");
  prefs.end();
  if (stored.length() != kBadgeIdLen) return false;
  memcpy(out_badge_id, stored.c_str(), kBadgeIdLen);
  return true;
}

void Provisioning::PollSerial() {
  if (!Serial.available()) return;
  const String line = Serial.readStringUntil('\n');
  if (!line.startsWith("PROV ")) return;

  if (line.startsWith("PROV id=")) {
    const String id = line.substring(8);
    String trimmed = id;
    trimmed.trim();
    if (trimmed.length() != kBadgeIdLen) {
      Serial.printf("ERR badge id must be exactly %u chars\n",
                    static_cast<unsigned>(kBadgeIdLen));
      return;
    }
    Preferences prefs;
    prefs.begin(kNvsNamespace, /*readOnly=*/false);
    prefs.putString(kNvsKeyBadgeId, trimmed);
    prefs.end();
    Serial.printf("OK badge_id=%s (reboot to apply)\n", trimmed.c_str());
  } else if (line.startsWith("PROV show")) {
    char id[kBadgeIdLen];
    if (Load(id)) {
      Serial.printf("badge_id=%.*s\n", static_cast<int>(kBadgeIdLen), id);
    } else {
      Serial.println("badge_id=<unprovisioned>");
    }
  } else {
    Serial.println("ERR commands: 'PROV id=<8 chars>', 'PROV show'");
  }
}

}  // namespace geogame::badge

#include "ring_light.h"

#include <FastLED.h>

#include "config.h"

namespace geogame::badge {
namespace {

CRGB g_leds[kRingLedCount];

constexpr CRGB kWarm = CRGB(255, 120, 20);   // wizard
constexpr CRGB kCold = CRGB(40, 120, 255);   // dementor
constexpr CRGB kOut = CRGB(80, 0, 0);        // out of play
constexpr CRGB kIdleDim = CRGB(8, 8, 8);
constexpr CRGB kStaleTint = CRGB(60, 60, 0); // stale/disconnected overlay
constexpr CRGB kLowBatt = CRGB(120, 20, 0);

CRGB RoleColor(uint8_t color) {
  switch (static_cast<RingColor>(color)) {
    case RingColor::kWarm:
      return kWarm;
    case RingColor::kCold:
      return kCold;
    default:
      return kIdleDim;
  }
}

}  // namespace

void RingLight::Begin() {
  FastLED.addLeds<WS2812B, kRingLedPin, GRB>(g_leds, kRingLedCount);
  FastLED.setBrightness(kRingBrightness);
  fill_solid(g_leds, kRingLedCount, kIdleDim);
  FastLED.show();
}

void RingLight::ApplyDownlink(const DownlinkPacket& state, uint32_t now_ms) {
  last_state_ = state;
  has_state_ = true;
  last_downlink_ms_ = now_ms;
}

void RingLight::Render(uint32_t now_ms, bool low_battery) {
  const bool stale =
      !has_state_ || (now_ms - last_downlink_ms_) > kDownlinkStaleMs;
  const bool blink_phase = (now_ms / 500) % 2 == 0;

  // Base frame: the last server-authored state (or idle before any).
  if (!has_state_ ||
      last_state_.pattern == static_cast<uint8_t>(RingPattern::kIdle)) {
    fill_solid(g_leds, kRingLedCount, kIdleDim);
  } else if (last_state_.pattern == static_cast<uint8_t>(RingPattern::kOut)) {
    fill_solid(g_leds, kRingLedCount, blink_phase ? kOut : CRGB::Black);
  } else {  // kEnergyFill
    const uint8_t lit =
        (static_cast<uint16_t>(last_state_.fill_pct) * kRingLedCount + 50) /
        100;
    const CRGB color = RoleColor(last_state_.color);
    for (uint8_t i = 0; i < kRingLedCount; ++i) {
      g_leds[i] = i < lit ? color : CRGB::Black;
    }
  }

  // Stale overlay: one slow-blinking marker LED, base frame preserved —
  // the wearer sees their last-known state plus "this is old".
  if (stale && blink_phase) {
    g_leds[0] = kStaleTint;
  }
  // Low battery: opposite marker LED in ember red.
  if (low_battery && blink_phase) {
    g_leds[kRingLedCount / 2] = kLowBatt;
  }

  // TODO(power): frame-rate limit + FastLED dithering off when battery
  // is low; measure ring draw at kRingBrightness on real hardware.
  FastLED.show();
}

}  // namespace geogame::badge

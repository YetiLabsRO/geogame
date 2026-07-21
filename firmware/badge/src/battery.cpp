#include "battery.h"

#include <Arduino.h>

#include "config.h"

namespace geogame::badge {

void Battery::Begin() {
  analogReadResolution(12);
  // TODO(hardware): confirm the ADC attenuation needed for the divider
  // output range (likely ADC_11db for ~0..2.1 V after a 2:1 divider).
  analogSetPinAttenuation(kBatteryAdcPin, ADC_11db);
}

uint8_t Battery::Percent() {
  // TODO(hardware): calibrate raw->volts against a bench supply; the
  // C3's ADC is nonlinear near the rails, use the eFuse cal if burned.
  const uint16_t raw = analogRead(kBatteryAdcPin);
  const float volts =
      (raw / 4095.0f) * 2.1f * kBatteryDividerRatio;  // placeholder scale
  float pct = (volts - kBatteryEmptyVolts) /
              (kBatteryFullVolts - kBatteryEmptyVolts) * 100.0f;
  if (pct < 0.0f) pct = 0.0f;
  if (pct > 100.0f) pct = 100.0f;
  // Light smoothing so the reported value doesn't jitter under load.
  if (last_pct_ == 0xFF) {
    last_pct_ = static_cast<uint8_t>(pct);
  } else {
    last_pct_ = static_cast<uint8_t>((last_pct_ * 3 + pct) / 4);
  }
  return last_pct_;
}

bool Battery::IsLow() {
  return last_pct_ != 0xFF && last_pct_ < kLowBatteryPct;
}

}  // namespace geogame::badge

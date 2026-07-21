// Battery sampling + percentage estimate for telemetry.
#pragma once

#include <stdint.h>

namespace geogame::badge {

class Battery {
 public:
  void Begin();
  // 0..100, or 0xFF while unknown (before the first stable sample).
  uint8_t Percent();
  bool IsLow();

 private:
  uint8_t last_pct_ = 0xFF;
};

}  // namespace geogame::badge

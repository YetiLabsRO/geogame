// IMU pipeline: gesture recognition, activity classification, and
// short-horizon dead-reckoning.
//
// Everything here is REPORTED, never acted on locally: the server
// decides what a cast gesture does and how activity feeds energy rules
// (wearable-badge spec). Dead-reckoned deltas are advisory telemetry.
#pragma once

#include <stdint.h>

#include "protocol.h"

namespace geogame::badge {

struct DeadReckoning {
  // Displacement estimate since last report, meters in a heading frame.
  // Coarse by design: step count x stride x heading from gyro yaw.
  float dx = 0.0f;
  float dy = 0.0f;
  uint16_t steps = 0;
};

class Imu {
 public:
  bool Begin();

  // Call at kImuSampleHz from the main loop.
  void Sample(uint32_t now_ms);

  // Gesture recognized since the last call (kNone when quiet). One
  // gesture per report window; recognition never triggers local effects.
  Gesture TakeGesture();

  // Current activity class from the rolling accel-variance window.
  Activity CurrentActivity() const { return activity_; }

  // Drain the dead-reckoning accumulator (zeroed after read).
  DeadReckoning TakeDeadReckoning();

 private:
  Activity activity_ = Activity::kUnknown;
  Gesture pending_gesture_ = Gesture::kNone;
  DeadReckoning dr_ = {};
  float accel_variance_window_[32] = {};
  size_t window_index_ = 0;
};

}  // namespace geogame::badge

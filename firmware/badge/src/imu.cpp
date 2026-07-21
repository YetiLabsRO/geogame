#include "imu.h"

#include <Wire.h>
#include <math.h>

#include "config.h"

// TODO(hardware): this file is a stub pipeline around thresholds that
// MUST be tuned on the real PCB (mounting orientation, strap slack,
// wrist vs. lanyard wear all shift the signal). The structure — sample,
// classify, accumulate, report — is what the pilot iterates on.

namespace geogame::badge {
namespace {

// Accel-magnitude variance thresholds (m/s^2)^2 for the activity
// classes. Placeholder values from desk experiments; tune in the pilot.
constexpr float kStillVarianceMax = 0.05f;
constexpr float kStandingVarianceMax = 0.8f;

// A "cast" flick: forward jerk above threshold followed by a stop
// within kGestureWindowMs. TODO(pilot): replace with a small matched
// filter once real recordings exist.
constexpr float kCastJerkThreshold = 25.0f;   // m/s^3, placeholder
constexpr float kDrainJerkThreshold = -25.0f; // reverse flick
constexpr uint32_t kGestureWindowMs = 400;
constexpr uint32_t kGestureCooldownMs = 1500;

// Dead-reckoning: fixed stride length; heading from integrated gyro
// yaw. Drifts within seconds — acceptable, it only smooths BETWEEN
// authoritative GPS/proximity updates and is reported as advisory.
constexpr float kStrideMeters = 0.7f;

uint32_t g_last_gesture_ms = 0;

}  // namespace

bool Imu::Begin() {
  Wire.begin(kImuSdaPin, kImuSclPin);
  // TODO(hardware): mpu.initialize() + WHO_AM_I check against the BOM
  // part; configure ±4g accel range, 250 dps gyro, on-chip LPF.
  return true;
}

void Imu::Sample(uint32_t now_ms) {
  // TODO(hardware): read accel+gyro over I2C. Placeholder keeps the
  // pipeline shape without a driver:
  const float ax = 0.0f, ay = 0.0f, az = 9.81f;
  const float gyro_z = 0.0f;
  (void)gyro_z;

  const float magnitude = sqrtf(ax * ax + ay * ay + az * az) - 9.81f;
  accel_variance_window_[window_index_++ % 32] = magnitude * magnitude;

  // --- Activity: rolling variance of accel magnitude ---
  float variance = 0.0f;
  for (float v : accel_variance_window_) variance += v;
  variance /= 32.0f;
  if (variance < kStillVarianceMax) {
    activity_ = Activity::kStill;
  } else if (variance < kStandingVarianceMax) {
    activity_ = Activity::kStanding;
  } else {
    activity_ = Activity::kRunning;
    // --- Dead-reckoning: crude step accumulation while moving ---
    // TODO(pilot): real step detection (peak picking on the filtered
    // magnitude) + gyro-yaw heading; this placeholder only counts time.
    dr_.steps += 1;
    dr_.dx += kStrideMeters;  // heading frame TBD
  }

  // --- Gesture: jerk thresholding with cooldown ---
  // TODO(hardware): compute jerk from consecutive accel samples; the
  // placeholders below never fire without a real driver.
  const float jerk = 0.0f;
  if (now_ms - g_last_gesture_ms > kGestureCooldownMs) {
    if (jerk > kCastJerkThreshold) {
      pending_gesture_ = Gesture::kCast;
      g_last_gesture_ms = now_ms;
    } else if (jerk < kDrainJerkThreshold) {
      pending_gesture_ = Gesture::kDrain;
      g_last_gesture_ms = now_ms;
    }
  }
  (void)kGestureWindowMs;
}

Gesture Imu::TakeGesture() {
  const Gesture gesture = pending_gesture_;
  pending_gesture_ = Gesture::kNone;
  return gesture;
}

DeadReckoning Imu::TakeDeadReckoning() {
  const DeadReckoning out = dr_;
  dr_ = {};
  return out;
}

}  // namespace geogame::badge

#ifndef SAFETY_WATCHDOG_GUARD__GUARD_POLICY_HPP_
#define SAFETY_WATCHDOG_GUARD__GUARD_POLICY_HPP_

#include <algorithm>
#include <cmath>

namespace safety_watchdog_guard
{

inline bool command_is_valid(double linear_x, double angular_z)
{
  return std::isfinite(linear_x) && std::isfinite(angular_z);
}

inline double clamp_axis(double value, double limit)
{
  return std::clamp(value, -limit, limit);
}

inline bool command_is_fresh(bool have_command, double age_sec, double timeout_sec)
{
  return have_command && std::isfinite(age_sec) && age_sec >= 0.0 && age_sec <= timeout_sec;
}

inline bool command_is_neutral(double linear_x, double angular_z, double epsilon)
{
  return command_is_valid(linear_x, angular_z) &&
         std::abs(linear_x) <= epsilon && std::abs(angular_z) <= epsilon;
}

}  // namespace safety_watchdog_guard

#endif  // SAFETY_WATCHDOG_GUARD__GUARD_POLICY_HPP_

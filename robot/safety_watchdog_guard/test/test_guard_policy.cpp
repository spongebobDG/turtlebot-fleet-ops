#include <limits>

#include "gtest/gtest.h"
#include "safety_watchdog_guard/guard_policy.hpp"

TEST(GuardPolicy, RejectsNonFiniteCommands)
{
  EXPECT_TRUE(safety_watchdog_guard::command_is_valid(0.05, -0.3));
  EXPECT_FALSE(safety_watchdog_guard::command_is_valid(
      std::numeric_limits<double>::quiet_NaN(), 0.0));
}

TEST(GuardPolicy, ClampsBothDirections)
{
  EXPECT_DOUBLE_EQ(safety_watchdog_guard::clamp_axis(0.8, 0.05), 0.05);
  EXPECT_DOUBLE_EQ(safety_watchdog_guard::clamp_axis(-0.8, 0.05), -0.05);
}

TEST(GuardPolicy, ExpiresAtTheConfiguredBoundary)
{
  EXPECT_TRUE(safety_watchdog_guard::command_is_fresh(true, 0.25, 0.25));
  EXPECT_FALSE(safety_watchdog_guard::command_is_fresh(true, 0.251, 0.25));
  EXPECT_FALSE(safety_watchdog_guard::command_is_fresh(false, 0.0, 0.25));
}

TEST(GuardPolicy, RequiresNeutralWithinEpsilon)
{
  EXPECT_TRUE(safety_watchdog_guard::command_is_neutral(0.0009, -0.0009, 0.001));
  EXPECT_FALSE(safety_watchdog_guard::command_is_neutral(0.0011, 0.0, 0.001));
}

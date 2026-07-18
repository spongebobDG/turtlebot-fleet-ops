cmake_minimum_required(VERSION 3.8)
project(safety_watchdog_guard)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rclcpp REQUIRED)

add_executable(watchdog_guard src/watchdog_guard.cpp)
target_compile_features(watchdog_guard PUBLIC cxx_std_17)
target_include_directories(watchdog_guard PUBLIC include)
ament_target_dependencies(watchdog_guard geometry_msgs rclcpp)

install(TARGETS watchdog_guard DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_guard_policy test/test_guard_policy.cpp)
  target_include_directories(test_guard_policy PUBLIC include)
endif()

ament_package()

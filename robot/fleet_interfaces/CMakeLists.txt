cmake_minimum_required(VERSION 3.8)
project(fleet_interfaces)

find_package(ament_cmake REQUIRED)
find_package(action_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/NavigateRobot.action"
  "msg/NavigationLease.msg"
  "msg/NavigationStatus.msg"
  "msg/MappingStatus.msg"
  "msg/RobotStatus.msg"
  "msg/SafetyStatus.msg"
  "srv/SetInitialPose.srv"
  "srv/SetMotionMode.srv"
  "srv/ManualCommand.srv"
  "srv/SaveMap.srv"
  "srv/SetOperatingProfile.srv"
  DEPENDENCIES action_msgs builtin_interfaces geometry_msgs std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()

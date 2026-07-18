#include <chrono>
#include <cmath>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>

#include "geometry_msgs/msg/twist.hpp"
#include "rclcpp/rclcpp.hpp"
#include "safety_watchdog_guard/guard_policy.hpp"

using namespace std::chrono_literals;

class WatchdogGuard : public rclcpp::Node
{
public:
  WatchdogGuard()
  : Node("safety_watchdog"),
    last_received_(std::chrono::steady_clock::now())
  {
    const auto input_topic = declare_parameter<std::string>(
      "input_topic", "/safety/watchdog_cmd_vel");
    const auto output_topic = declare_parameter<std::string>("output_topic", "/cmd_vel");
    timeout_sec_ = declare_parameter<double>("timeout_sec", 0.25);
    max_linear_x_ = declare_parameter<double>("max_linear_x", 0.05);
    max_angular_z_ = declare_parameter<double>("max_angular_z", 0.3);
    const auto publish_rate_hz = declare_parameter<double>("publish_rate_hz", 20.0);

    if (input_topic.empty() || output_topic.empty() || input_topic == output_topic) {
      throw std::invalid_argument("guard input and output topics must be non-empty and different");
    }
    if (!std::isfinite(timeout_sec_) || timeout_sec_ <= 0.0 ||
      !std::isfinite(max_linear_x_) || max_linear_x_ <= 0.0 ||
      !std::isfinite(max_angular_z_) || max_angular_z_ <= 0.0 ||
      !std::isfinite(publish_rate_hz) || publish_rate_hz <= 0.0)
    {
      throw std::invalid_argument("guard limits, timeout, and publish rate must be positive and finite");
    }

    publisher_ = create_publisher<geometry_msgs::msg::Twist>(output_topic, 10);
    subscription_ = create_subscription<geometry_msgs::msg::Twist>(
      input_topic,
      10,
      std::bind(&WatchdogGuard::on_command, this, std::placeholders::_1));
    const auto period = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::duration<double>(1.0 / publish_rate_hz));
    timer_ = create_wall_timer(period, std::bind(&WatchdogGuard::on_timer, this));

    publish_stop();
    RCLCPP_INFO(
      get_logger(),
      "Safety output guard ready: input=%s output=%s timeout=%.3fs",
      input_topic.c_str(), output_topic.c_str(), timeout_sec_);
  }

  ~WatchdogGuard() override
  {
    if (rclcpp::ok()) {
      publish_stop();
    }
  }

private:
  void on_command(const geometry_msgs::msg::Twist::SharedPtr message)
  {
    if (!safety_watchdog_guard::command_is_valid(message->linear.x, message->angular.z)) {
      have_command_ = false;
      return;
    }
    command_.linear.x = safety_watchdog_guard::clamp_axis(message->linear.x, max_linear_x_);
    command_.angular.z = safety_watchdog_guard::clamp_axis(message->angular.z, max_angular_z_);
    last_received_ = std::chrono::steady_clock::now();
    have_command_ = true;
  }

  void on_timer()
  {
    const auto age = std::chrono::duration<double>(
      std::chrono::steady_clock::now() - last_received_).count();
    const bool fresh = safety_watchdog_guard::command_is_fresh(
      have_command_, age, timeout_sec_);
    if (fresh) {
      publisher_->publish(command_);
    } else {
      publish_stop();
    }
    if (fresh != was_fresh_) {
      if (fresh) {
        RCLCPP_INFO(get_logger(), "Fresh watchdog policy output received");
      } else {
        RCLCPP_ERROR(get_logger(), "Watchdog policy output timed out; publishing zero");
      }
      was_fresh_ = fresh;
    }
  }

  void publish_stop()
  {
    publisher_->publish(geometry_msgs::msg::Twist());
  }

  double timeout_sec_{0.25};
  double max_linear_x_{0.05};
  double max_angular_z_{0.3};
  bool have_command_{false};
  bool was_fresh_{false};
  std::chrono::steady_clock::time_point last_received_;
  geometry_msgs::msg::Twist command_;
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr publisher_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr subscription_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<WatchdogGuard>());
  rclcpp::shutdown();
  return 0;
}

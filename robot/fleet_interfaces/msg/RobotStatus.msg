# Fleet-wide health levels.
uint8 LEVEL_OK=0
uint8 LEVEL_WARN=1
uint8 LEVEL_ERROR=2

# Publish time and robot identity.
std_msgs/Header header
string robot_id
string hostname
uint8 level

# Battery values are normalized to percent in the 0..100 range.
# Unknown numeric values use -1.0 rather than NaN for JSON compatibility.
bool battery_received
bool battery_fresh
bool battery_valid
builtin_interfaces/Time battery_last_received
float32 battery_age_sec
float32 battery_percent
float32 battery_voltage
bool battery_present

# Planar odometry snapshot.
bool odom_received
bool odom_fresh
bool odom_valid
builtin_interfaces/Time odom_last_received
float32 odom_age_sec
float64 position_x
float64 position_y
float64 yaw
float64 linear_velocity
float64 angular_velocity

# LiDAR summary. scan_min_range is -1.0 when no valid point exists.
bool scan_received
bool scan_fresh
bool scan_valid
builtin_interfaces/Time scan_last_received
float32 scan_age_sec
uint32 scan_valid_points
float32 scan_min_range

# Raspberry Pi host resources.
float32 cpu_percent
float32 memory_percent
float32 disk_percent
float32 load_average_1m
uint64 uptime_sec

# Wi-Fi information comes from the Linux wireless interface when available.
bool wifi_valid
string wifi_interface
float32 wifi_signal_dbm
float32 wifi_quality_percent

# Stable machine-readable identifiers such as ODOM_STALE or LOW_BATTERY.
string[] fault_codes

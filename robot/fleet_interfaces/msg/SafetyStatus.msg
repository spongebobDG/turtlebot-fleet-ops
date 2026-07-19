uint8 MODE_TIMEOUT=0
uint8 MODE_ACTIVE=1
uint8 MODE_ESTOP=2
uint8 MODE_WAITING_NEUTRAL=3

std_msgs/Header header
string robot_id
uint8 mode
bool estop_active
bool motion_armed

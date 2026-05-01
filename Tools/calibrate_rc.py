import socket
import threading
import json
import time

# =============================================================================
# CALIBRATION CONFIG
# =============================================================================
TELEMETRY_PORT = 4212

# We need to send dummy packets to the ESP32 so it registers our IP
# and knows where to send the telemetry data back to.
ESP32_IP = "127.0.0.1"   # ✏️ CHANGE TO YOUR ESP32's IP
ESP32_PORT = 4210

# Thread-safe storage for the latest stick values
latest_rc = {
    "roll": 1500,
    "pitch": 1500,
    "throttle": 1000,
    "yaw": 1500
}
last_rc_time = 0.0

# =============================================================================
# BACKGROUND NETWORKING
# =============================================================================
def telemetry_listener():
    global last_rc_time
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", TELEMETRY_PORT))

    while True:
        try:
            data, _ = sock.recvfrom(1024)
            payload = json.loads(data.decode("utf-8"))

            if payload.get("type") == "rc":
                latest_rc["roll"]     = payload.get("roll", 1500)
                latest_rc["pitch"]    = payload.get("pitch", 1500)
                latest_rc["throttle"] = payload.get("throttle", 1000)
                latest_rc["yaw"]      = payload.get("yaw", 1500)
                last_rc_time          = time.time()
        except Exception:
            pass

def keep_esp32_alive():
    """Sends a neutral dummy packet to the ESP32 every 200ms so it doesn't trigger failsafe."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        payload = "1500,1500,1000,1500,1000"
        sock.sendto(payload.encode("utf-8"), (ESP32_IP, ESP32_PORT))
        time.sleep(0.2)

# =============================================================================
# WIZARD LOGIC
# =============================================================================
def main():
    print("======================================================")
    print("  DRONE RC CALIBRATION WIZARD")
    print("======================================================\n")
    print("Starting background telemetry listeners...")

    threading.Thread(target=telemetry_listener, daemon=True).start()
    threading.Thread(target=keep_esp32_alive, daemon=True).start()

    print("Waiting for RC telemetry from ESP32...")
    while time.time() - last_rc_time > 1.0:
        time.sleep(0.5)

    print("✅ RC Telemetry received! Let's calibrate.\n")
    print("⚠️  WARNING: REMOVE PROPELLERS BEFORE PROCEEDING ⚠️\n")

    results = {}

    def prompt_user(message, axis):
        input(f"👉 {message} (Press ENTER when holding...)")
        val = latest_rc[axis]
        print(f"   Recorded {axis.upper()}: {val}\n")
        return val

    # 1. Hover Throttle
    results["throttle_hover"] = prompt_user("Move THROTTLE to the position where the drone hovers", "throttle")

    # 2. Forward/Backward
    results["pitch_forward"]  = prompt_user("Push PITCH (Right Stick) UP to a good FORWARD speed", "pitch")
    results["pitch_backward"] = prompt_user("Pull PITCH (Right Stick) DOWN to a good BACKWARD speed", "pitch")

    # 3. Left/Right
    results["roll_left"]      = prompt_user("Push ROLL (Right Stick) LEFT to a good LEFT strafe speed", "roll")
    results["roll_right"]     = prompt_user("Push ROLL (Right Stick) RIGHT to a good RIGHT strafe speed", "roll")

    print("======================================================")
    print("🎉 CALIBRATION COMPLETE! 🎉")
    print("Copy and paste these values into main_bci.py:\n")

    print(f"""
        # Inside apply_command() in main_bci.py:

        # [TAKEOFF] Target
        target_rc_channels["throttle"] = {results["throttle_hover"]:.1f}   # Hover throttle

        # [FORWARD] Target
        target_rc_channels["pitch"] = {results["pitch_forward"]:.1f}       # Forward pitch authority

        # [BACKWARD] Target
        target_rc_channels["pitch"] = {results["pitch_backward"]:.1f}       # Backward pitch authority

        # [LEFT] Target
        target_rc_channels["roll"]  = {results["roll_left"]:.1f}       # Left roll authority

        # [RIGHT] Target
        target_rc_channels["roll"]  = {results["roll_right"]:.1f}       # Right roll authority
    """)
    print("======================================================")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCalibration cancelled.")
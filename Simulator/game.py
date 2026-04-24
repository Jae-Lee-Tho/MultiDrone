# Simulator_Bridge/sim_bridge.py
import socket
import vgamepad as vg

# Network config
UDP_IP = "127.0.0.1"
UDP_PORT = 4210
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

gamepad = vg.VX360Gamepad()

def map_channel_to_joystick(rc_value):
    """ Converts RC channel (1000-2000) to Gamepad float (-1.0 to 1.0) """
    rc_value = max(1000, min(2000, int(rc_value)))
    return (rc_value - 1500) / 500.0

print("=======================================")
print(" 🎮 Virtual Gamepad Bridge Started 🎮")
print("=======================================")
print(f"Listening for Ground Station on {UDP_IP}:{UDP_PORT}...")
print("Waiting for data...\n")

try:
    while True:
        data, addr = sock.recvfrom(1024)
        channels = data.decode('utf-8').split(',')

        if len(channels) >= 5:
            roll     = float(channels[0])
            pitch    = float(channels[1])
            throttle = float(channels[2])
            yaw      = float(channels[3])
            arm_aux  = float(channels[4])

            # Map to Xbox logic (-1.0 to 1.0)
            left_x = map_channel_to_joystick(yaw)
            left_y = map_channel_to_joystick(throttle)
            right_x = map_channel_to_joystick(roll)
            right_y = map_channel_to_joystick(pitch)

            # Apply to virtual gamepad
            gamepad.left_joystick_float(x_value_float=left_x, y_value_float=left_y)
            gamepad.right_joystick_float(x_value_float=right_x, y_value_float=right_y)

            # Map the "ARM" channel to the 'A' Button
            if arm_aux > 1500:
                gamepad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
                btn_a = "PRESSED"
            else:
                gamepad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
                btn_a = "RELEASED"

            gamepad.update()

            # --- REAL-TIME TELEMETRY DISPLAY ---
            # This overwrites the current line in the terminal so it doesn't spam your screen
            debug_string = f"Xbox Output -> L-Stick[Y:{left_y:+.2f} X:{left_x:+.2f}] | R-Stick[Y:{right_y:+.2f} X:{right_x:+.2f}] | A-Button: {btn_a}   "
            print(f"\r{debug_string}", end="", flush=True)

except KeyboardInterrupt:
    print("\n\nShutting down Virtual Gamepad.")
    gamepad.reset()
    gamepad.update()
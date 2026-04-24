# Raspberry_Pi/Raspberry_Pi.py
import socket
import time
import threading
import json
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# ==========================================
# 1. EXPERIMENT SETTINGS
# ==========================================
# Change this to "VOICE_ONLY", "EMG_ONLY", or "BOTH"
EXPERIMENT_MODE = "VOICE_ONLY"

# How long the drone moves in a direction before auto-stopping (seconds)
MOVEMENT_DURATION = 3.0

# ==========================================
# 2. NETWORK CONFIGURATION (UDP)
# ==========================================
ESP32_IP = "127.0.0.1"
ESP32_PORT = 4210
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

channels = {
    "roll": 1500,
    "pitch": 1500,
    "throttle": 1000,
    "yaw": 1500,
    "arm": 1000
}

# ==========================================
# 3. COMMAND STATE & FUSION VARIABLES
# ==========================================
# SAFETY SYSTEM: Drone must be "GROUNDED" or "AIRBORNE"
drone_state = "GROUNDED"

active_voice_cmd = None
active_voice_time = 0

active_emg_cmd = None
active_emg_time = 0

last_movement_time = 0
is_moving = False

# ==========================================
# 4. SENSORS (VOICE & EMG LOGIC)
# ==========================================
print("[System] Loading Vosk Model...")
model = Model("vosk-model-small-en-us-0.15")
list_of_commands = '["take off", "land", "forward", "backward", "[unk]", "right", "left", "stop"]'
rec = KaldiRecognizer(model, 16000, list_of_commands)

def map_speech_to_command(text: str):
    text = text.lower().strip()
    if "take off" in text or "takeoff" in text: return "TAKEOFF"
    elif "land" in text: return "LAND"
    elif "forward" in text: return "FORWARD"
    elif "backward" in text: return "BACKWARD"
    elif "left" in text: return "LEFT"
    elif "right" in text: return "RIGHT"
    elif "stop" in text: return "STOP"
    return None

def audio_callback(indata, frames, time_info, status):
    """ Runs automatically in the background capturing voice """
    global active_voice_cmd, active_voice_time
    if rec.AcceptWaveform(bytes(indata)):
        result = json.loads(rec.Result())
        text = result.get("text", "").strip()
        if text:
            cmd = map_speech_to_command(text)
            if cmd:
                print(f"[VOICE HEARD] -> {cmd}")
                active_voice_cmd = cmd
                active_voice_time = time.time()

def emg_polling_thread():
    """
    PLACEHOLDER FOR EMG LOGIC
    """
    global active_emg_cmd, active_emg_time
    while True:
        # --- YOUR EMG CODE GOES HERE ---
        time.sleep(0.05)

# ==========================================
# 5. EXECUTION & BROADCAST LOOP
# ==========================================
def apply_command(command: str):
    global last_movement_time, is_moving, channels, drone_state

    # ----------------------------------------------------
    # EMERGENCY OVERRIDE - Bypasses all state restrictions
    # ----------------------------------------------------
    if command == "STOP":
        print("\n[🚨 EMERGENCY STOP 🚨] Forcing immediate landing!")
        channels["throttle"] = 1000
        channels["arm"] = 1000
        channels["pitch"] = 1500
        channels["roll"] = 1500
        channels["yaw"] = 1500
        is_moving = False
        drone_state = "GROUNDED"
        return

    # ----------------------------------------------------
    # GROUNDED STATE LOGIC
    # ----------------------------------------------------
    if drone_state == "GROUNDED":
        if command != "TAKEOFF":
            print(f"\n[BLOCKED] Drone is GROUNDED. Cannot execute '{command}'. Say 'Take off' first.")
            return

        print(f"\n[EXECUTING] => TAKEOFF. Drone is now AIRBORNE.")
        channels["arm"] = 2000
        channels["throttle"] = 1600
        drone_state = "AIRBORNE"

    # ----------------------------------------------------
    # AIRBORNE STATE LOGIC
    # ----------------------------------------------------
    elif drone_state == "AIRBORNE":
        if command == "TAKEOFF":
            print("\n[IGNORED] Drone is already airborne.")
            return

        print(f"\n[EXECUTING] => {command}")

        if command == "LAND":
            channels["throttle"] = 1000
            channels["arm"] = 1000
            channels["pitch"] = 1500
            channels["roll"] = 1500
            is_moving = False
            drone_state = "GROUNDED"
            print("[STATE] Drone is now GROUNDED.")

        elif command == "FORWARD":
            channels["pitch"] = 1700
            last_movement_time = time.time()
            is_moving = True

        elif command == "BACKWARD":
            channels["pitch"] = 1300
            last_movement_time = time.time()
            is_moving = True

        elif command == "LEFT":
            channels["roll"] = 1300
            last_movement_time = time.time()
            is_moving = True

        elif command == "RIGHT":
            channels["roll"] = 1700
            last_movement_time = time.time()
            is_moving = True

def main_control_loop():
    global active_voice_cmd, active_emg_cmd, is_moving, drone_state

    print(f"[Raspberry Pi] Broadcasting UDP stream ({EXPERIMENT_MODE} MODE)...")
    print(f"[STATE] Drone is initialized and GROUNDED.")

    while True:
        now = time.time()

        # 1. Clear old commands if they weren't processed within 1 second
        if now - active_voice_time > 1.0: active_voice_cmd = None
        if now - active_emg_time > 1.0: active_emg_cmd = None

        final_cmd = None

        # 2. EVALUATE COMMANDS
        # Absolute Priority: If *either* sensor triggers an emergency STOP, execute immediately!
        if active_voice_cmd == "STOP" or active_emg_cmd == "STOP":
            final_cmd = "STOP"
            active_voice_cmd = None
            active_emg_cmd = None

        else:
            # Standard Evaluation Mode
            if EXPERIMENT_MODE == "VOICE_ONLY" and active_voice_cmd:
                final_cmd = active_voice_cmd
                active_voice_cmd = None

            elif EXPERIMENT_MODE == "EMG_ONLY" and active_emg_cmd:
                final_cmd = active_emg_cmd
                active_emg_cmd = None

            elif EXPERIMENT_MODE == "BOTH":
                if active_voice_cmd and active_emg_cmd:
                    if active_voice_cmd == active_emg_cmd:
                        print(f"[FUSION MATCH] Both say {active_voice_cmd}! Executing.")
                        final_cmd = active_voice_cmd
                    else:
                        print(f"[FUSION MISMATCH] Voice:{active_voice_cmd} | EMG:{active_emg_cmd}. Ignoring.")

                    active_voice_cmd = None
                    active_emg_cmd = None

        # 3. Apply the final decided command
        if final_cmd:
            apply_command(final_cmd)

        # 4. AUTO-STOP LOGIC (Return to stable hover after moving)
        if is_moving and (now - last_movement_time > MOVEMENT_DURATION):
            print("[AUTO-STOP] Returning Pitch/Roll to neutral hover (1500).")
            channels["pitch"] = 1500
            channels["roll"] = 1500
            is_moving = False

        # 5. Broadcast to the Drone at exactly 50Hz
        payload = f"{channels['roll']},{channels['pitch']},{channels['throttle']},{channels['yaw']},{channels['arm']}"
        sock.sendto(payload.encode('utf-8'), (ESP32_IP, ESP32_PORT))

        time.sleep(0.02)

# ==========================================
# 6. SYSTEM START
# ==========================================
if __name__ == '__main__':
    print("\n==========================================")
    print(f" 🚀 Ground Station: {EXPERIMENT_MODE} MODE 🚀")
    print("==========================================")

    threading.Thread(target=emg_polling_thread, daemon=True).start()

    try:
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=audio_callback
        ):
            main_control_loop()

    except KeyboardInterrupt:
        print("\n[Raspberry Pi] Shutting down.")
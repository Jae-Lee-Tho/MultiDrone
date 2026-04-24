# Raspberry_Pi/Raspberry_Pi.py
import socket
import time
import threading
import json
from enum import Enum

import sounddevice as sd
from vosk import Model, KaldiRecognizer

# ==========================================
# 1. EXPERIMENT SETTINGS
# ==========================================
# Change this to "VOICE_ONLY", "EMG_ONLY", or "BOTH"
class ExperimentMode(Enum):
    VOICE_ONLY = "VOICE_ONLY"
    EMG_ONLY = "EMG_ONLY"
    BOTH = "BOTH"

EXPERIMENT_MODE = ExperimentMode.VOICE_ONLY

# How long the drone moves in a direction before auto-stopping (seconds)
MOVEMENT_DURATION = 1.0

# ==========================================
# 2. NETWORK CONFIGURATION (UDP)
# ==========================================
ESP32_IP = "127.0.0.1"
ESP32_PORT = 4210
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

channels = {"roll": 1500, "pitch": 1500, "throttle": 1000, "yaw": 1500, "arm": 1000}

# ==========================================
# 3. COMMAND STATE & FUSION VARIABLES
# ==========================================
# SAFETY SYSTEM: Drone must be "GROUNDED" or "AIRBORNE"
DRONE_STATE = "GROUNDED"

ACTIVE_VOICE_CMD = None
ACTIVE_VOICE_TIME = 0

ACTIVE_EMG_CMD = None
ACTIVE_EMG_TIME = 0

LAST_MOVEMENT_TIME = 0
IS_MOVING = False

# ==========================================
# 4. SENSORS (VOICE & EMG LOGIC)
# ==========================================
print("[System] Loading Vosk Model...")
model = Model("vosk-model-small-en-us-0.15")
list_of_commands = (
    '["take off", "land", "forward", "backward", "[unk]", "right", "left", "stop"]'
)
rec = KaldiRecognizer(model, 16000, list_of_commands)


def map_speech_to_command(text: str):
    text = text.lower().strip()
    if "take off" in text or "takeoff" in text:
        return "TAKEOFF"
    elif "land" in text:
        return "LAND"
    elif "forward" in text:
        return "FORWARD"
    elif "backward" in text:
        return "BACKWARD"
    elif "left" in text:
        return "LEFT"
    elif "right" in text:
        return "RIGHT"
    elif "stop" in text:
        return "STOP"
    return None


def audio_callback(indata, frames, time_info, status):
    """Runs automatically in the background capturing voice"""
    global ACTIVE_VOICE_CMD, ACTIVE_VOICE_TIME
    if rec.AcceptWaveform(bytes(indata)):
        result = json.loads(rec.Result())
        text = result.get("text", "").strip()
        if text:
            cmd = map_speech_to_command(text)
            if cmd:
                print(f"[VOICE HEARD] -> {cmd}")
                ACTIVE_VOICE_CMD = cmd
                ACTIVE_VOICE_TIME = time.time()


def emg_polling_thread():
    """
    PLACEHOLDER FOR EMG LOGIC
    """
    global ACTIVE_EMG_CMD, ACTIVE_EMG_TIME
    while True:
        # --- YOUR EMG CODE GOES HERE ---
        time.sleep(0.05)


# ==========================================
# 5. EXECUTION & BROADCAST LOOP
# ==========================================
def apply_command(command: str):
    global LAST_MOVEMENT_TIME, IS_MOVING, channels, DRONE_STATE

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
        IS_MOVING = False
        DRONE_STATE = "GROUNDED"
        return

    # ----------------------------------------------------
    # GROUNDED STATE LOGIC
    # ----------------------------------------------------
    if DRONE_STATE == "GROUNDED":
        if command != "TAKEOFF":
            print(
                f"\n[BLOCKED] Drone is GROUNDED. Cannot execute '{command}'. Say 'Take off' first."
            )
            return

        print(f"\n[EXECUTING] => TAKEOFF. Drone is now AIRBORNE.")
        channels["arm"] = 2000
        channels["throttle"] = 1600
        DRONE_STATE = "AIRBORNE"

    # ----------------------------------------------------
    # AIRBORNE STATE LOGIC
    # ----------------------------------------------------
    elif DRONE_STATE == "AIRBORNE":
        if command == "TAKEOFF":
            print("\n[IGNORED] Drone is already airborne.")
            return

        print(f"\n[EXECUTING] => {command}")

        if command == "LAND":
            channels["throttle"] = 1000
            channels["arm"] = 1000
            channels["pitch"] = 1500
            channels["roll"] = 1500
            IS_MOVING = False
            DRONE_STATE = "GROUNDED"
            print("[STATE] Drone is now GROUNDED.")

        elif command == "FORWARD":
            channels["pitch"] = 1700
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True

        elif command == "BACKWARD":
            channels["pitch"] = 1300
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True

        elif command == "LEFT":
            channels["roll"] = 1300
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True

        elif command == "RIGHT":
            channels["roll"] = 1700
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True


def main_control_loop():
    global ACTIVE_VOICE_CMD, ACTIVE_EMG_CMD, IS_MOVING, DRONE_STATE

    print(f"[Raspberry Pi] Broadcasting UDP stream ({EXPERIMENT_MODE} MODE)...")
    print(f"[STATE] Drone is initialized and GROUNDED.")

    while True:
        now = time.time()

        # 1. Clear old commands if they weren't processed within 1 second
        if now - ACTIVE_VOICE_TIME > 1.0:
            ACTIVE_VOICE_CMD = None
        if now - ACTIVE_EMG_TIME > 1.0:
            ACTIVE_EMG_CMD = None

        final_cmd = None

        # 2. EVALUATE COMMANDS
        # Absolute Priority: If *either* sensor triggers an emergency STOP, execute immediately!
        if ACTIVE_VOICE_CMD == "STOP" or ACTIVE_EMG_CMD == "STOP":
            final_cmd = "STOP"
            ACTIVE_VOICE_CMD = None
            ACTIVE_EMG_CMD = None

        else:
            # Standard Evaluation Mode
            if EXPERIMENT_MODE == "VOICE_ONLY" and ACTIVE_VOICE_CMD:
                final_cmd = ACTIVE_VOICE_CMD
                ACTIVE_VOICE_CMD = None

            elif EXPERIMENT_MODE == "EMG_ONLY" and ACTIVE_EMG_CMD:
                final_cmd = ACTIVE_EMG_CMD
                ACTIVE_EMG_CMD = None

            elif EXPERIMENT_MODE == "BOTH":
                if ACTIVE_VOICE_CMD and ACTIVE_EMG_CMD:
                    if ACTIVE_VOICE_CMD == ACTIVE_EMG_CMD:
                        print(f"[FUSION MATCH] Both say {ACTIVE_VOICE_CMD}! Executing.")
                        final_cmd = ACTIVE_VOICE_CMD
                    else:
                        print(
                            f"[FUSION MISMATCH] Voice:{ACTIVE_VOICE_CMD} | EMG:{ACTIVE_EMG_CMD}. Ignoring."
                        )

                    ACTIVE_VOICE_CMD = None
                    ACTIVE_EMG_CMD = None

        # 3. Apply the final decided command
        if final_cmd:
            apply_command(final_cmd)

        # 4. AUTO-STOP LOGIC (Return to stable hover after moving)
        if IS_MOVING and (now - LAST_MOVEMENT_TIME > MOVEMENT_DURATION):
            print("[AUTO-STOP] Returning Pitch/Roll to neutral hover (1500).")
            channels["pitch"] = 1500
            channels["roll"] = 1500
            IS_MOVING = False

        # 5. Broadcast to the Drone at exactly 50Hz
        payload = f"{channels['roll']},{channels['pitch']},{channels['throttle']},{channels['yaw']},{channels['arm']}"
        sock.sendto(payload.encode("utf-8"), (ESP32_IP, ESP32_PORT))

        time.sleep(0.02)


# ==========================================
# 6. SYSTEM START
# ==========================================
if __name__ == "__main__":
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
            callback=audio_callback,
        ):
            main_control_loop()

    except KeyboardInterrupt:
        print("\n[Raspberry Pi] Shutting down.")

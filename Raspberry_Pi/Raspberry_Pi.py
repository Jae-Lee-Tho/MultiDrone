# Raspberry_Pi/raspberry_pi.py
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
class ExperimentMode(Enum):
    VOICE_ONLY = "VOICE_ONLY"
    EMG_ONLY   = "EMG_ONLY"
    BOTH       = "BOTH"

# How long the drone moves in a direction before auto-stopping (seconds)
ACTION_DURATION = 1.0

EXPERIMENT_MODE = ExperimentMode.VOICE_ONLY

# ==========================================
# 2. NETWORK CONFIGURATION (UDP)
# ==========================================
ESP32_IP   = "127.0.0.1"
ESP32_PORT = 4210
sock       = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

channels = {
    "roll":     1500,
    "pitch":    1500,
    "throttle": 1000,
    "yaw":      1500,
    "arm":      1000,
}

# ==========================================
# 3. COMMAND STATE & FUSION VARIABLES
# ==========================================
class DroneState(Enum):
    GROUNDED = "GROUNDED"
    AIRBORNE = "AIRBORNE"

DRONE_STATE = DroneState.GROUNDED

ACTIVE_VOICE_CMD   = None
ACTIVE_VOICE_TIME  = 0.0

ACTIVE_EMG_CMD     = None
ACTIVE_EMG_TIME    = 0.0

LAST_MOVEMENT_TIME = 0.0
IS_MOVING          = False

# ==========================================
# 4. COMMAND DEFINITIONS
# ==========================================
class Command(Enum):
    TAKEOFF  = "TAKEOFF"
    LAND     = "LAND"
    FORWARD  = "FORWARD"
    BACKWARD = "BACKWARD"
    LEFT     = "LEFT"
    RIGHT    = "RIGHT"
    STOP     = "STOP"

# ==========================================
# 5. SENSORS (VOICE & EMG LOGIC)
# ==========================================
print("[System] Loading Vosk Model...")
model = Model("vosk-model-small-en-us-0.15")

custom_grammar =[cmd.value.lower() for cmd in Command] + ["take off", "[unk]"]
list_of_commands = json.dumps(custom_grammar)
rec = KaldiRecognizer(model, 16000, list_of_commands)


def map_speech_to_command(text: str) -> Command | None:
    """Map a raw speech string to a Command enum member."""
    text = text.lower().strip()
    if "take off" in text or "takeoff" in text:
        return Command.TAKEOFF
    elif "land" in text:
        return Command.LAND
    elif "forward" in text:
        return Command.FORWARD
    elif "backward" in text:
        return Command.BACKWARD
    elif "left" in text:
        return Command.LEFT
    elif "right" in text:
        return Command.RIGHT
    elif "stop" in text:
        return Command.STOP
    return None


def audio_callback(indata, _frames, _time_info, _status) -> None:
    """Runs automatically in the background capturing voice."""
    global ACTIVE_VOICE_CMD, ACTIVE_VOICE_TIME
    if rec.AcceptWaveform(bytes(indata)):
        result = json.loads(rec.Result())
        text   = result.get("text", "").strip()
        if text:
            cmd = map_speech_to_command(text)
            if cmd:
                print(f"[VOICE HEARD] -> {cmd.value}")
                ACTIVE_VOICE_CMD  = cmd
                ACTIVE_VOICE_TIME = time.time()


def emg_polling_thread() -> None:
    """
    PLACEHOLDER FOR EMG LOGIC
    """
    global ACTIVE_EMG_CMD, ACTIVE_EMG_TIME
    while True:
        time.sleep(0.05)


# ==========================================
# 6. CHANNEL HELPERS
# ==========================================
def _neutral_movement() -> None:
    """Return pitch and roll to stable hover values."""
    channels["pitch"] = 1500
    channels["roll"]  = 1500


def _disarm() -> None:
    """Cut throttle and disarm the drone."""
    channels["throttle"] = 1000
    channels["arm"]      = 1000
    _neutral_movement()


# ==========================================
# 7. COMMAND EXECUTION
# ==========================================
def apply_command(command: Command) -> None:
    global IS_MOVING, LAST_MOVEMENT_TIME, DRONE_STATE

    # --------------------------------------------------
    # EMERGENCY STOP — bypasses all state restrictions
    # --------------------------------------------------
    if command is Command.STOP:
        print("\n[EMERGENCY STOP] Forcing immediate landing")
        _disarm()
        IS_MOVING   = False
        DRONE_STATE = DroneState.GROUNDED
        return

    # --------------------------------------------------
    # GROUNDED STATE
    # --------------------------------------------------
    if DRONE_STATE is DroneState.GROUNDED:
        if command is not Command.TAKEOFF:
            print(
                f"\n[BLOCKED] Drone is GROUNDED. "
                f"Cannot execute '{command.value}'. Say 'Take off' first."
            )
            return

        print("\n[EXECUTING] => TAKEOFF. Drone is now AIRBORNE.")
        channels["arm"]      = 2000
        channels["throttle"] = 1600
        DRONE_STATE = DroneState.AIRBORNE

    # --------------------------------------------------
    # AIRBORNE STATE
    # --------------------------------------------------
    elif DRONE_STATE is DroneState.AIRBORNE:
        if command is Command.TAKEOFF:
            print("\n[IGNORED] Drone is already airborne.")
            return

        print(f"\n[EXECUTING] => {command.value}")

        if command is Command.LAND:
            _disarm()
            IS_MOVING   = False
            DRONE_STATE = DroneState.GROUNDED
            print("[STATE] Drone is now GROUNDED.")

        elif command is Command.FORWARD:
            channels["pitch"] = 1700
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True

        elif command is Command.BACKWARD:
            channels["pitch"] = 1300
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True

        elif command is Command.LEFT:
            channels["roll"] = 1300
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True

        elif command is Command.RIGHT:
            channels["roll"] = 1700
            LAST_MOVEMENT_TIME = time.time()
            IS_MOVING = True


# ==========================================
# 8. MAIN CONTROL LOOP
# ==========================================
def main_control_loop() -> None:
    global ACTIVE_VOICE_CMD, ACTIVE_EMG_CMD, IS_MOVING

    print(f"[Raspberry Pi] Broadcasting UDP stream ({EXPERIMENT_MODE.value} MODE)...")
    print("[STATE] Drone is initialized and GROUNDED.")

    while True:
        now = time.time()

        # 1. Commands lasts for a limited duration to prevent stale commands from lingering
        if now - ACTIVE_VOICE_TIME > 1.0:
            ACTIVE_VOICE_CMD = None
        if now - ACTIVE_EMG_TIME > 1.0:
            ACTIVE_EMG_CMD = None

        final_cmd = None

        # 2. COMMAND EVALUATION
        # Emergency STOP from either sensor takes absolute priority
        if ACTIVE_VOICE_CMD is Command.STOP or ACTIVE_EMG_CMD is Command.STOP:
            final_cmd        = Command.STOP
            ACTIVE_VOICE_CMD = None
            ACTIVE_EMG_CMD   = None

        else:
            if EXPERIMENT_MODE is ExperimentMode.VOICE_ONLY and ACTIVE_VOICE_CMD:
                final_cmd        = ACTIVE_VOICE_CMD
                ACTIVE_VOICE_CMD = None

            elif EXPERIMENT_MODE is ExperimentMode.EMG_ONLY and ACTIVE_EMG_CMD:
                final_cmd      = ACTIVE_EMG_CMD
                ACTIVE_EMG_CMD = None

            elif EXPERIMENT_MODE is ExperimentMode.BOTH:
                if ACTIVE_VOICE_CMD and ACTIVE_EMG_CMD:
                    if ACTIVE_VOICE_CMD is ACTIVE_EMG_CMD:
                        print(f"[FUSION MATCH] Both say {ACTIVE_VOICE_CMD.value}! Executing.")
                        final_cmd = ACTIVE_VOICE_CMD
                    else:
                        print(
                            f"[FUSION MISMATCH] "
                            f"Voice: {ACTIVE_VOICE_CMD.value} | "
                            f"EMG: {ACTIVE_EMG_CMD.value}. Ignoring."
                        )
                    ACTIVE_VOICE_CMD = None
                    ACTIVE_EMG_CMD   = None

        # 3. Apply the final decided command
        if final_cmd:
            apply_command(final_cmd)

        # 4. AUTO-STOP: return to stable hover after ACTION_DURATION elapses
        if IS_MOVING and (now - LAST_MOVEMENT_TIME > ACTION_DURATION):
            print("[AUTO-STOP] Returning Pitch/Roll to neutral hover (1500).")
            _neutral_movement()
            IS_MOVING = False

        payload = (
            f"{channels['roll']},"
            f"{channels['pitch']},"
            f"{channels['throttle']},"
            f"{channels['yaw']},"
            f"{channels['arm']}"
        )
        sock.sendto(payload.encode("utf-8"), (ESP32_IP, ESP32_PORT))

        time.sleep(0.02)


# ==========================================
# 9. SYSTEM START
# ==========================================
if __name__ == "__main__":
    print("\n==========================================")
    print(f"Ground Station: {EXPERIMENT_MODE.value} MODE")
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
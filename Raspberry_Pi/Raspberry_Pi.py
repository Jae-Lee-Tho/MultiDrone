# =============================================================================
# DRONE VOICE CONTROL — RASPBERRY PI
# =============================================================================
#
# WHAT THIS FILE DOES:
#   This is the "brain" of the system. It runs on a Raspberry Pi, listens to
#   a microphone for voice commands, and sends RC channel values over Wi-Fi
#   (UDP) to the ESP32, which forwards them to the flight controller.
#
# HOW THE FULL SYSTEM FITS TOGETHER:
#
#   [Microphone] ──► [Raspberry Pi] ──► Wi-Fi UDP ──► [ESP32] ──► UART ──► [Betaflight FC] ──► [Motors]
#   [EMG Sensor] ──►        ↑
#                      (this file)
#
# BEFORE RUNNING ON REAL HARDWARE — CHECKLIST:
#   □ 1. Change ESP32_IP from "127.0.0.1" to "192.168.4.1"
#         (that is the ESP32's default SoftAP IP when it creates its own hotspot)
#         OR change it to whatever IP your phone hotspot assigns the ESP32.
#   □ 2. Download the Vosk model and place it next to this file:
#         https://alphacephei.com/vosk/models  →  vosk-model-small-en-us-0.15
#   □ 3. Calibrate the RC channel values in apply_command() using the rc_sniffer
#         tool while flying with your physical Radiomaster controller. The values
#         currently in the code are reasonable starting estimates, not measured.
#   □ 4. If using EMG, fill in emg_polling_thread() with your sensor's read logic.
#   □ 5. Set EXPERIMENT_MODE to match what you are testing (see section 1 below).
#
# DEPENDENCIES (install with pip):
#   pip install sounddevice vosk
#
# =============================================================================

import socket
import time
import threading
import json
from enum import Enum

import sounddevice as sd
from vosk import Model, KaldiRecognizer


# =============================================================================
# SECTION 1 — EXPERIMENT MODE
# =============================================================================
# Controls which sensors are used to drive the drone.
#
#   VOICE_ONLY  → only voice commands count. EMG is ignored.
#   EMG_ONLY    → only EMG gestures count. Voice is ignored.
#   BOTH        → BOTH sensors must agree on the same command before it
#                 executes. If they disagree, the command is dropped.
#                 This is the safest mode for a live demo.
#
# ✏️  CHANGE THIS to switch between experiment phases:
# =============================================================================

class ExperimentMode(Enum):
    VOICE_ONLY = "VOICE_ONLY"
    EMG_ONLY   = "EMG_ONLY"
    BOTH       = "BOTH"

EXPERIMENT_MODE = ExperimentMode.VOICE_ONLY   # ✏️  change here


# How many seconds a directional command (forward, left, etc.) stays active
# before the drone automatically returns to a neutral hover.
# Increase this if the drone doesn't move far enough; decrease if it overshoots.
ACTION_DURATION = 1.0   # seconds  ✏️  tune this on real hardware


# =============================================================================
# SECTION 2 — NETWORK CONFIGURATION
# =============================================================================
# The Pi sends a CSV string of RC channel values over UDP to the ESP32.
# Format sent: "roll,pitch,throttle,yaw,arm"  e.g. "1500,1700,1600,1500,2000"
#
# SIMULATION:  ESP32_IP = "127.0.0.1"   (everything on one computer)
# REAL HARDWARE (ESP32 SoftAP):  ESP32_IP = "192.168.4.1"
# REAL HARDWARE (phone hotspot): ESP32_IP = <IP assigned to ESP32 by hotspot>
#                                 Check your phone's connected-devices list.
#
# ✏️  Update ESP32_IP before running on real hardware.
# =============================================================================

ESP32_IP   = "127.0.0.1"   # ✏️  change to "192.168.4.1" for real hardware
ESP32_PORT = 4210           # must match UDP_PORT in ESP32_Firmware.ino

_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# =============================================================================
# SECTION 3 — RC CHANNEL VALUES
# =============================================================================
# RC channels are the "language" Betaflight understands. Each value is a
# number from 1000 to 2000, where 1500 is centre/neutral.
#
# These are the current channel values that get sent to the ESP32 every loop.
# They start in a safe, disarmed state and are modified by apply_command().
#
# Channel mapping (matches Betaflight's default layout):
#   roll     → CH1 → left/right tilt     (1000=full left,  1500=centre, 2000=full right)
#   pitch    → CH2 → forward/back tilt   (1000=full back,  1500=centre, 2000=full forward)
#   throttle → CH3 → motor speed         (1000=motors off, 2000=full power)
#   yaw      → CH4 → rotation            (1000=spin left,  1500=centre, 2000=spin right)
#   arm      → CH5 → arm/disarm switch   (1000=disarmed,   2000=armed)
# =============================================================================

rc_channels = {
    "roll":     1500,   # neutral
    "pitch":    1500,   # neutral
    "throttle": 1000,   # motors off (safe default)
    "yaw":      1500,   # neutral
    "arm":      1000,   # disarmed (safe default)
}


# =============================================================================
# SECTION 4 — DRONE STATE MACHINE
# =============================================================================
# The drone is always in one of two states: GROUNDED or AIRBORNE.
# This prevents dangerous commands like "move forward" being executed
# while the drone is still sitting on the ground.
# =============================================================================

class DroneState(Enum):
    GROUNDED = "GROUNDED"   # motors off, won't accept movement commands
    AIRBORNE = "AIRBORNE"   # hovering, accepts movement commands

drone_state = DroneState.GROUNDED


# =============================================================================
# SECTION 5 — AVAILABLE COMMANDS
# =============================================================================

class Command(Enum):
    TAKEOFF  = "TAKEOFF"
    LAND     = "LAND"
    FORWARD  = "FORWARD"
    BACKWARD = "BACKWARD"
    LEFT     = "LEFT"
    RIGHT    = "RIGHT"
    STOP     = "STOP"   # emergency stop — works from any state


# =============================================================================
# SECTION 6 — SENSOR STATE
# =============================================================================
# When a sensor detects a command, it writes to these variables.
# The main control loop reads them, decides what to do, then clears them.
#
# ACTIVE_VOICE_CMD / ACTIVE_EMG_CMD:  the most recent detected command (or None)
# ACTIVE_VOICE_TIME / ACTIVE_EMG_TIME: when that command was detected
#
# Commands older than COMMAND_EXPIRY_SECONDS are discarded automatically,
# so a missed word or stale gesture doesn't execute seconds later.
# =============================================================================

COMMAND_EXPIRY_SECONDS = 1.0

# Voice sensor state (written by audio_callback, read by main loop)
active_voice_cmd  = None
active_voice_time = float('-inf')   # float('-inf') means "never set"

# EMG sensor state (written by emg_polling_thread, read by main loop)
active_emg_cmd  = None
active_emg_time = float('-inf')

# Movement tracking (used by auto-stop logic)
last_movement_time = 0.0
is_moving          = False


# =============================================================================
# SECTION 7 — VOICE RECOGNITION
# =============================================================================

print("[System] Loading Vosk speech recognition model...")
_vosk_model = Model("vosk-model-small-en-us-0.15")

# Restrict the recognizer to only these words so it doesn't mishear anything.
_grammar    = json.dumps([cmd.value.lower() for cmd in Command] + ["take off", "[unk]"])
_recognizer = KaldiRecognizer(_vosk_model, 16000, _grammar)


def _map_speech_to_command(text: str) -> Command | None:
    """
    Convert a recognized speech string into a Command enum value.
    Returns None if the text doesn't match any known command.
    """
    text = text.lower().strip()
    if "take off" in text or "takeoff" in text: return Command.TAKEOFF
    if "land"     in text:                       return Command.LAND
    if "forward"  in text:                       return Command.FORWARD
    if "backward" in text:                       return Command.BACKWARD
    if "left"     in text:                       return Command.LEFT
    if "right"    in text:                       return Command.RIGHT
    if "stop"     in text:                       return Command.STOP
    return None


def audio_callback(indata, _frames, _time_info, _status) -> None:
    """
    Called automatically by sounddevice every time a new audio chunk arrives.
    Feeds audio into Vosk and updates active_voice_cmd if a command is heard.
    This runs in a background thread — do not call it directly.
    """
    global active_voice_cmd, active_voice_time

    if _recognizer.AcceptWaveform(bytes(indata)):
        result = json.loads(_recognizer.Result())
        text   = result.get("text", "").strip()
        if text:
            cmd = _map_speech_to_command(text)
            if cmd:
                print(f"[VOICE] Heard: '{text}' → {cmd.value}")
                active_voice_cmd  = cmd
                active_voice_time = time.time()


# =============================================================================
# SECTION 8 — EMG SENSOR
# =============================================================================
# ✏️  THIS SECTION NEEDS TO BE FILLED IN before EMG mode will work.
#
# Replace the body of the while loop below with code that:
#   1. Reads a signal from your EMG sensor (e.g. via GPIO, SPI, or serial)
#   2. Classifies the gesture into one of the Command enum values
#   3. Sets active_emg_cmd and active_emg_time, exactly like audio_callback does
#
# Example structure once you have sensor reading working:
#
#   raw_signal = read_emg_sensor()          # your sensor read call here
#   gesture    = classify_gesture(raw_signal)  # your classification logic here
#   if gesture:
#       active_emg_cmd  = gesture
#       active_emg_time = time.time()
#       print(f"[EMG] Detected gesture → {gesture.value}")
# =============================================================================

def emg_polling_thread() -> None:
    """
    Runs in a background thread, continuously polling the EMG sensor.
    Currently a placeholder — see Section 8 above for what to fill in.
    """
    global active_emg_cmd, active_emg_time

    while True:
        # ✏️  Replace this with real EMG sensor reading + gesture classification
        time.sleep(0.05)   # poll at 20Hz — adjust to match your sensor's sample rate


# =============================================================================
# SECTION 9 — RC CHANNEL HELPERS
# =============================================================================

def _set_neutral_movement() -> None:
    """Return pitch and roll to centre (1500), putting the drone into a stable hover."""
    rc_channels["pitch"] = 1500
    rc_channels["roll"]  = 1500


def _disarm() -> None:
    """
    Cut throttle and disarm. Safe to call at any time.
    The drone will drop if airborne — only call this for landing or emergency stop.
    """
    rc_channels["throttle"] = 1000
    rc_channels["arm"]      = 1000
    _set_neutral_movement()


# =============================================================================
# SECTION 10 — COMMAND EXECUTION
# =============================================================================
# Translates a Command enum value into actual RC channel values.
#
# ✏️  TUNING THESE VALUES is the most important step on real hardware.
#     Use the rc_sniffer.js tool while flying with your physical Radiomaster
#     controller to find what values actually produce the behaviour you want,
#     then replace the numbers below.
#
# Current values are reasonable estimates for a 5" drone on 6S:
#   Takeoff throttle 1600 ≈ 50% throttle — likely too high, probably closer to 1400
#   Forward/back pitch  ±200 from centre — may need to be smaller (±100) indoors
#   Left/right roll     ±200 from centre — same, tune for your space
# =============================================================================

def apply_command(command: Command) -> None:
    global is_moving, last_movement_time, drone_state

    # ------------------------------------------------------------------
    # EMERGENCY STOP
    # Bypasses all state checks. Immediately disarms from any state.
    # Triggered by saying "stop" from either sensor.
    # ------------------------------------------------------------------
    if command is Command.STOP:
        print("\n[EMERGENCY STOP] Disarming immediately.")
        _disarm()
        is_moving   = False
        drone_state = DroneState.GROUNDED
        return

    # ------------------------------------------------------------------
    # GROUNDED — only TAKEOFF is accepted
    # ------------------------------------------------------------------
    if drone_state is DroneState.GROUNDED:

        if command is not Command.TAKEOFF:
            print(f"[BLOCKED] Drone is grounded. Say 'take off' first. (Ignored: {command.value})")
            return

        print("\n[TAKEOFF] Arming and climbing to hover.")
        rc_channels["arm"]      = 2000   # arm switch ON
        rc_channels["throttle"] = 1600   # ✏️  tune: real hover throttle is likely 1350–1450
        drone_state = DroneState.AIRBORNE

    # ------------------------------------------------------------------
    # AIRBORNE — movement and landing commands accepted
    # ------------------------------------------------------------------
    elif drone_state is DroneState.AIRBORNE:

        if command is Command.TAKEOFF:
            print("[IGNORED] Already airborne.")
            return

        if command is Command.LAND:
            print("\n[LAND] Disarming and landing.")
            _disarm()
            is_moving   = False
            drone_state = DroneState.GROUNDED
            return

        # Directional commands — move for ACTION_DURATION then auto-return to hover
        print(f"[MOVE] {command.value}")

        if command is Command.FORWARD:
            rc_channels["pitch"] = 1600   # ✏️  tune: push forward gently, try 1550 first indoors
        elif command is Command.BACKWARD:
            rc_channels["pitch"] = 1400   # ✏️  tune: same, opposite direction
        elif command is Command.LEFT:
            rc_channels["roll"]  = 1400   # ✏️  tune
        elif command is Command.RIGHT:
            rc_channels["roll"]  = 1600   # ✏️  tune

        last_movement_time = time.time()
        is_moving          = True


# =============================================================================
# SECTION 11 — MAIN CONTROL LOOP
# =============================================================================
# Runs at 50Hz (every 20ms). Each iteration:
#   1. Expires stale sensor commands
#   2. Decides which command to execute based on EXPERIMENT_MODE
#   3. Applies the command (updates rc_channels)
#   4. Auto-stops directional movement after ACTION_DURATION
#   5. Sends the current rc_channels to the ESP32 over UDP
# =============================================================================

def main_control_loop() -> None:
    global active_voice_cmd, active_emg_cmd, is_moving

    print(f"\n[Control Loop] Running in {EXPERIMENT_MODE.value} mode.")
    print(f"[Control Loop] Sending UDP to {ESP32_IP}:{ESP32_PORT} at 50Hz.")
    print("[State] Drone is GROUNDED and disarmed. Say 'take off' to begin.\n")

    while True:
        now = time.time()

        # ------------------------------------------------------------------
        # STEP 1: Expire stale commands
        # If a command was detected more than COMMAND_EXPIRY_SECONDS ago,
        # clear it so it doesn't execute late.
        # ------------------------------------------------------------------
        if now - active_voice_time > COMMAND_EXPIRY_SECONDS:
            active_voice_cmd = None
        if now - active_emg_time > COMMAND_EXPIRY_SECONDS:
            active_emg_cmd = None

        # ------------------------------------------------------------------
        # STEP 2: Decide which command to execute
        # ------------------------------------------------------------------
        final_cmd = None

        # Emergency stop takes absolute priority over everything
        if active_voice_cmd is Command.STOP or active_emg_cmd is Command.STOP:
            final_cmd         = Command.STOP
            active_voice_cmd  = None
            active_emg_cmd    = None

        elif EXPERIMENT_MODE is ExperimentMode.VOICE_ONLY:
            if active_voice_cmd:
                final_cmd        = active_voice_cmd
                active_voice_cmd = None

        elif EXPERIMENT_MODE is ExperimentMode.EMG_ONLY:
            if active_emg_cmd:
                final_cmd      = active_emg_cmd
                active_emg_cmd = None

        elif EXPERIMENT_MODE is ExperimentMode.BOTH:
            # Both sensors must agree on the same command for it to execute.
            # If they disagree, both are discarded and nothing happens.
            if active_voice_cmd and active_emg_cmd:
                if active_voice_cmd is active_emg_cmd:
                    print(f"[FUSION] Both sensors agree: {active_voice_cmd.value} → executing.")
                    final_cmd = active_voice_cmd
                else:
                    print(f"[FUSION] Sensors disagree — Voice: {active_voice_cmd.value} | EMG: {active_emg_cmd.value} → ignoring.")
                active_voice_cmd = None
                active_emg_cmd   = None

        # ------------------------------------------------------------------
        # STEP 3: Apply the decided command
        # ------------------------------------------------------------------
        if final_cmd:
            apply_command(final_cmd)

        # ------------------------------------------------------------------
        # STEP 4: Auto-stop directional movement after ACTION_DURATION
        # Returns pitch and roll to neutral so the drone hovers in place.
        # ------------------------------------------------------------------
        if is_moving and (now - last_movement_time > ACTION_DURATION):
            print("[AUTO-STOP] Returning to neutral hover.")
            _set_neutral_movement()
            is_moving = False

        # ------------------------------------------------------------------
        # STEP 5: Send current channel values to ESP32 over UDP
        # Format: "roll,pitch,throttle,yaw,arm"
        # The ESP32 encodes this into an MSP packet and forwards to Betaflight.
        # ------------------------------------------------------------------
        payload = (
            f"{rc_channels['roll']},"
            f"{rc_channels['pitch']},"
            f"{rc_channels['throttle']},"
            f"{rc_channels['yaw']},"
            f"{rc_channels['arm']}"
        )
        _udp_socket.sendto(payload.encode("utf-8"), (ESP32_IP, ESP32_PORT))

        time.sleep(0.02)   # 50Hz — do not change, the ESP32 and FC expect this rate


# =============================================================================
# SECTION 12 — ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  Drone Voice Control — {EXPERIMENT_MODE.value} MODE")
    print(f"  Target: {ESP32_IP}:{ESP32_PORT}")
    print("=" * 60)

    # Start the EMG polling thread (runs in background, does nothing until
    # you fill in emg_polling_thread() in Section 8)
    threading.Thread(target=emg_polling_thread, daemon=True).start()

    # Start the microphone stream and run the main loop.
    # sounddevice calls audio_callback() automatically whenever new audio arrives.
    try:
        with sd.RawInputStream(
            samplerate=16000,   # Vosk requires 16kHz
            blocksize=8000,     # process audio in ~0.5s chunks
            dtype="int16",
            channels=1,         # mono microphone
            callback=audio_callback,
        ):
            main_control_loop()

    except KeyboardInterrupt:
        print("\n[System] Ctrl+C received — shutting down.")
        _disarm()
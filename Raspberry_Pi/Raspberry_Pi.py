# =============================================================================
# DRONE GROUND CONTROL STATION — LAPTOP (VOICE + EEG FUSION)
# =============================================================================

import socket
import time
import threading
import json
import numpy as np
import datetime
from enum import Enum

import sounddevice as sd
from scipy.signal import butter, sosfiltfilt, iirnotch, sosfilt, detrend
from vosk import Model, KaldiRecognizer
from pylsl import resolve_byprop, StreamInlet
from sklearn.cross_decomposition import CCA


# =============================================================================
# SECTION 1 — EXPERIMENT MODE & CONFIG
# =============================================================================

class ExperimentMode(Enum):
    VOICE_ONLY  = "VOICE_ONLY"
    EEG_ONLY    = "EEG_ONLY"
    BOTH        = "BOTH"
    PHYSICAL_RC = "PHYSICAL_RC"

EXPERIMENT_MODE = ExperimentMode.BOTH

# How long (in seconds) a directional command is held before auto-stopping.
ACTION_DURATION = 1.0  # ✏️ tune

# MOVEMENT STYLE CONFIGURATION
# Set to True for cinematic, gliding movements.
# Set to False for instant, aggressive "jerk" movements.
ENABLE_SMOOTHING = True

# How aggressively the actual RC values chase the target values each loop tick.
# Lower = smoother/slower ramp up. Higher = more aggressive/faster.
# Only used if ENABLE_SMOOTHING is True.
SMOOTHING_FACTOR = 0.10  # ✏️ tune  (range: 0.01 – 1.0)


# =============================================================================
# SECTION 2 — NETWORK & TELEMETRY CONFIGURATION
# =============================================================================

ESP32_IP   = "127.0.0.1"   # ✏️  change to ESP32 IP for real hardware
ESP32_PORT = 4210

_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ---------------------------------------------------------
# NEW: TEST RUNNER INTEGRATION
# We stream a unified state object to the Test Runner Script
# ---------------------------------------------------------
TEST_RUNNER_IP   = "127.0.0.1"
TEST_RUNNER_PORT = 4211
_test_runner_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Listen for ESP32 Telemetry
TELEMETRY_PORT = 4212
_telemetry_rx_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_telemetry_rx_socket.settimeout(1.0)   # Wake up every second so we can detect silence
_telemetry_rx_socket.bind(("0.0.0.0", TELEMETRY_PORT))

LOG_FILENAME = f"flight_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

# Expanded to hold Attitude, Analog, AND Physical RC Sticks for the Test Runner
latest_telemetry = {
    "vbat": 0.0,
    "current": 0.0,
    "roll": 0.0,
    "pitch": 0.0,
    "yaw": 0.0,
    "rc_roll": 1500,
    "rc_pitch": 1500,
    "rc_throttle": 1000,
    "rc_yaw": 1500
}


# =============================================================================
# SECTION 3 — RC CHANNEL VALUES & DRONE STATE
# =============================================================================

# The actual values currently sent to the drone over UDP.
rc_channels = {
    "roll":     1500.0,
    "pitch":    1500.0,
    "throttle": 1000.0,
    "yaw":      1500.0,   # Tracked for future use
    "arm":      1000,
}

# The "desired" values that commands write to. The main loop interpolates
# rc_channels toward these targets each tick (when smoothing is enabled).
target_rc_channels = {
    "roll":     1500.0,
    "pitch":    1500.0,
    "throttle": 1000.0,
    "yaw":      1500.0,
}

class DroneState(Enum):
    GROUNDED = "GROUNDED"
    AIRBORNE = "AIRBORNE"

drone_state = DroneState.GROUNDED


# =============================================================================
# SECTION 4 — FREQUENCY-TO-COMMAND MAPPING
# =============================================================================
#
# SSVEP stimulus frequencies and their associated drone commands.
#
# KEY DESIGN CONSTRAINT — avoid the alpha band (8–12 Hz):
#   The occipital cortex produces strong alpha oscillations (~10 Hz) during
#   rest and eye closure. Stimulus frequencies inside that band risk being
#   masked by or confused with spontaneous alpha activity.
#
#   We therefore keep all frequencies either ABOVE 13 Hz or BELOW 7 Hz,
#   leaving a clean gap around the 8–12 Hz alpha range.
#
# Current layout:
#   High-band  (>13 Hz) : TAKEOFF 20 Hz | LAND 15 Hz | FORWARD 14 Hz
#   Low-band   (<7  Hz) : BACKWARD 6 Hz | LEFT 5.5 Hz | RIGHT 5 Hz | STOP 4.5 Hz
#
# ✏️ tune — if your display refresh rate or amplifier changes, update these
#           so that each frequency is an exact integer multiple of your
#           stimulus frame rate (e.g. 60 / N Hz).

class Command(Enum):
    TAKEOFF  = "TAKEOFF"
    LAND     = "LAND"
    FORWARD  = "FORWARD"
    BACKWARD = "BACKWARD"
    LEFT     = "LEFT"
    RIGHT    = "RIGHT"
    STOP     = "STOP"

FREQ_TO_COMMAND = {
    20.0:  Command.TAKEOFF,   # 60 / 3  — well above alpha band
    15.0:  Command.LAND,      # 60 / 4  — well above alpha band
    14.0:  Command.FORWARD,   # 60 / ~4.3 — clear of alpha band
     6.0:  Command.BACKWARD,  # 60 / 10 — below alpha band
     5.5:  Command.LEFT,      # 60 / ~10.9 — below alpha band
     5.0:  Command.RIGHT,     # 60 / 12 — below alpha band
     4.5:  Command.STOP,      # 60 / ~13.3 — below alpha band
}


# =============================================================================
# SECTION 5 — SENSOR STATE
# =============================================================================

# A voice or EEG command is discarded if it is older than this many seconds.
# Prevents stale detections from firing unexpectedly after a delay.
COMMAND_EXPIRY_SECONDS = 2.5  # ✏️ tune

active_voice_cmd  = None
active_voice_time = float('-inf')

active_eeg_cmd  = None
active_eeg_time = float('-inf')

last_movement_time = 0.0
is_moving          = False

# NEW: Track the live CCA correlation score for the Test Runner graph
latest_eeg_score = 0.0


# =============================================================================
# SECTION 6 — TELEMETRY BACKGROUND LISTENER
# =============================================================================

# How many consecutive silent seconds before we log a warning.
TELEMETRY_SILENCE_WARN_SECONDS = 5  # ✏️ tune

def telemetry_listener_thread() -> None:
    print(f"[Telemetry] Listening for Betaflight data on port {TELEMETRY_PORT}...")
    print(f"[Telemetry] Logging all data to: {LOG_FILENAME}")

    last_rx_time = time.time()

    while True:
        try:
            data, _addr = _telemetry_rx_socket.recvfrom(1024)
            last_rx_time = time.time()

            payload_str  = data.decode("utf-8")
            telemetry_data = json.loads(payload_str)
            telemetry_data["system_time"] = time.time()

            if telemetry_data.get("type") == "analog":
                latest_telemetry["vbat"]    = telemetry_data.get("vbat", 0.0)
                latest_telemetry["current"] = telemetry_data.get("current", 0.0)

            elif telemetry_data.get("type") == "attitude":
                latest_telemetry["roll"]  = telemetry_data.get("roll",  0.0)
                latest_telemetry["pitch"] = telemetry_data.get("pitch", 0.0)
                latest_telemetry["yaw"]   = telemetry_data.get("yaw", 0.0)

            # NEW: Physical controller stick values mapping!
            elif telemetry_data.get("type") == "rc":
                latest_telemetry["rc_roll"]     = telemetry_data.get("roll", 1500)
                latest_telemetry["rc_pitch"]    = telemetry_data.get("pitch", 1500)
                latest_telemetry["rc_throttle"] = telemetry_data.get("throttle", 1000)
                latest_telemetry["rc_yaw"]      = telemetry_data.get("yaw", 1500)

            with open(LOG_FILENAME, "a") as f:
                f.write(json.dumps(telemetry_data) + "\n")

        except TimeoutError:
            # Socket woke up with no data — check how long we've been silent.
            silent_for = time.time() - last_rx_time
            if silent_for >= TELEMETRY_SILENCE_WARN_SECONDS:
                print(f"[Telemetry] WARNING: No data received for {silent_for:.0f}s. "
                      "Check Betaflight MSP bridge.")

        except Exception:
            pass


# =============================================================================
# SECTION 7 — VOICE RECOGNITION (VOSK)
# =============================================================================

print("[System] Loading Vosk speech recognition model...")
_vosk_model = Model("vosk-model-small-en-us-0.15")
_grammar    = json.dumps([cmd.value.lower() for cmd in Command] +["take off", "[unk]"])
_recognizer = KaldiRecognizer(_vosk_model, 16000, _grammar)

def _map_speech_to_command(text: str) -> Command | None:
    text = text.lower().strip()
    if "take off" in text or "takeoff" in text: return Command.TAKEOFF
    if "land"     in text:                      return Command.LAND
    if "forward"  in text:                      return Command.FORWARD
    if "backward" in text:                      return Command.BACKWARD
    if "left"     in text:                      return Command.LEFT
    if "right"    in text:                      return Command.RIGHT
    if "stop"     in text:                      return Command.STOP
    return None

def audio_callback(indata, _frames, _time_info, _status) -> None:
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
# SECTION 8 — EEG BRAINWAVE PROCESSING (SSVEP + CCA)
# =============================================================================

# --- 8a. EEG signal processing parameters ---

# Occipital channel indices in the OpenBCI data stream (0-based).
# Adjust to match your headset's electrode layout.
OCCIPITAL_INDICES = [5, 6, 7]  # ✏️ tune — depends on headset/cap layout

# Length of the EEG window fed into CCA each iteration.
# Longer window → better frequency resolution, more latency.
WINDOW_SECONDS = 2.0  # ✏️ tune  (seconds)

# Fraction of the window to advance after a successful detection.
# Smaller overlap = more responsive but more CPU.
WINDOW_STEP_FRACTION = 0.5  # ✏️ tune  (0.0 – 1.0, fraction of window length)

# Minimum CCA canonical correlation to accept a frequency as a real SSVEP signal.
# Too low → false positives from noise. Too high → missed detections.
CONFIDENCE_THRESHOLD = 0.50  # ✏️ tune  (range: 0.0 – 1.0)

# Number of harmonics included in the CCA reference signals.
# More harmonics = richer template, better detection, slightly more CPU.
NUM_HARMONICS = 3  # ✏️ tune

# --- 8b. Preprocessing filter parameters ---
#
# Pipeline order: detrend → notch (60 Hz) → bandpass → CAR → CCA
#
# Bandpass bounds are chosen to cover all SSVEP stimulus frequencies
# (currently 4.5–20 Hz) with margin, while excluding:
#   • DC drift and slow movement artefacts  (below 4 Hz)
#   • High-frequency muscle/line noise      (above 30 Hz)
#   • Alpha band (8–12 Hz) is NOT excluded here — we avoid it
#     at the stimulus-frequency selection level (Section 4).
#
BANDPASS_LOW_HZ  =  6.0   # ✏️ tune — lower bound; must be below lowest stimulus freq
BANDPASS_HIGH_HZ = 30.0   # ✏️ tune — upper bound; must be above highest stimulus freq
BANDPASS_ORDER   =  4     # ✏️ tune — Butterworth filter order (higher = sharper rolloff)

# Powerline notch frequency. Use 60 Hz (Americas/Japan) or 50 Hz (Europe/Asia).
NOTCH_FREQ_HZ = 60.0   # ✏️ tune — 60 for US/Canada, 50 for Europe/Asia
NOTCH_Q       = 30.0   # ✏️ tune — quality factor; higher = narrower notch


def _build_filters(sample_rate: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Pre-compute and return the bandpass and notch filter coefficients.
    Called once when the EEG stream is connected, not on every window.
    Returns (bandpass_sos, notch_sos).
    """
    nyq = sample_rate / 2.0

    # Butterworth bandpass as second-order sections (SOS) for numerical stability.
    bandpass_sos = butter(
        BANDPASS_ORDER,[BANDPASS_LOW_HZ / nyq, BANDPASS_HIGH_HZ / nyq],
        btype="band",
        output="sos",
    )

    # IIR notch to suppress powerline interference.
    b_notch, a_notch = iirnotch(NOTCH_FREQ_HZ / nyq, NOTCH_Q)
    # Convert ba → sos for consistent filtering interface.
    from scipy.signal import tf2sos
    notch_sos = tf2sos(b_notch, a_notch)

    return bandpass_sos, notch_sos


def preprocess_eeg_window(
    eeg_data: np.ndarray,
    bandpass_sos: np.ndarray,
    notch_sos: np.ndarray,
) -> np.ndarray:
    """
    Apply the full preprocessing pipeline to a raw EEG window.

    Pipeline:
      1. Baseline detrend  — removes linear drift / DC offset per channel.
      2. Notch filter      — suppresses powerline interference (60 Hz by default).
      3. Bandpass filter   — passes only the SSVEP-relevant frequency range.
      4. Common Average Reference (CAR) — subtracts the mean across channels
                                          sample-by-sample to cancel noise
                                          common to all electrodes.

    Parameters
    ----------
    eeg_data     : (samples x channels) raw EEG array
    bandpass_sos : pre-built bandpass SOS coefficients
    notch_sos    : pre-built notch SOS coefficients

    Returns
    -------
    cleaned : (samples x channels) preprocessed array
    """
    # 1. Detrend: remove linear trend per channel (axis=0 operates per column).
    cleaned = detrend(eeg_data, axis=0)

    # 2. Notch filter: zero-phase to avoid phase distortion on SSVEP signals.
    cleaned = sosfiltfilt(notch_sos, cleaned, axis=0)

    # 3. Bandpass filter: zero-phase Butterworth.
    cleaned = sosfiltfilt(bandpass_sos, cleaned, axis=0)

    # 4. Common Average Reference: subtract the instantaneous mean across channels.
    #    This suppresses noise that appears identically on every electrode
    #    (e.g. movement artefacts, power fluctuations).
    cleaned = cleaned - cleaned.mean(axis=1, keepdims=True)

    return cleaned


# --- 8c. SSVEP / CCA analysis ---

def _generate_reference_signals(
    length: int,
    sample_rate: float,
    target_freq: float,
) -> np.ndarray:
    """
    Build the sinusoidal reference matrix for a given stimulus frequency.
    Includes NUM_HARMONICS sine/cosine pairs → shape (length, 2*NUM_HARMONICS).
    """
    t = np.arange(length) / sample_rate
    refs =[]
    for h in range(1, NUM_HARMONICS + 1):
        refs.append(np.sin(2 * np.pi * h * target_freq * t))
        refs.append(np.cos(2 * np.pi * h * target_freq * t))
    return np.array(refs).T


def analyze_ssvep_window(
    eeg_data: np.ndarray,
    sample_rate: float,
) -> tuple[float | None, float]:
    """
    Run CCA against reference signals for every candidate frequency and
    return the best match if it clears CONFIDENCE_THRESHOLD.

    Parameters
    ----------
    eeg_data    : preprocessed (samples × channels) EEG array
    sample_rate : sampling rate in Hz

    Returns
    -------
    (best_freq, score) — best_freq is None if no candidate clears the threshold.
    """
    global latest_eeg_score
    samples = eeg_data.shape[0]
    best_freq  = None
    best_score = 0.0

    for freq in FREQ_TO_COMMAND:
        y_ref = _generate_reference_signals(samples, sample_rate, freq)

        cca = CCA(n_components=1)
        cca.fit(eeg_data, y_ref)
        X_c, Y_c = cca.transform(eeg_data, y_ref)

        # Canonical correlation between the first component pair.
        score = float(np.corrcoef(X_c[:, 0], Y_c[:, 0])[0, 1])

        if score > best_score:
            best_score = score
            best_freq  = freq

    # ALWAYS update the global score so the Test Runner can graph it continuously
    latest_eeg_score = best_score

    if best_score >= CONFIDENCE_THRESHOLD:
        return best_freq, best_score

    return None, best_score


# --- 8d. EEG polling thread ---

def eeg_polling_thread() -> None:
    """
    Continuously resolves an OpenBCI LSL stream (retrying indefinitely),
    buffers incoming samples, and feeds rolling windows into the SSVEP
    pipeline. Updates active_eeg_cmd when a command is detected.
    """
    global active_eeg_cmd, active_eeg_time

    # Retry loop — keeps looking until the OpenBCI GUI starts broadcasting.
    inlet = None
    while inlet is None:
        print("[EEG] Looking for OpenBCI LSL stream on the local network...")
        streams = resolve_byprop('type', 'EEG', timeout=5.0)

        if streams:
            inlet = StreamInlet(streams[0])
        else:
            print("[EEG] Stream not found. Retrying in 5 seconds... "
                  "(ensure OpenBCI GUI is broadcasting)")
            time.sleep(5)

    srate          = inlet.info().nominal_srate() or 250.0  # ✏️ tune fallback if auto-detect fails
    window_samples = int(srate * WINDOW_SECONDS)
    step_samples   = int(srate * WINDOW_SECONDS * WINDOW_STEP_FRACTION)
    data_buffer    =[]

    # Build filters once — avoids repeated coefficient computation per window.
    bandpass_sos, notch_sos = _build_filters(srate)

    print(f"[EEG] Connected! Sample rate: {srate:.0f} Hz | "
          f"Window: {WINDOW_SECONDS}s ({window_samples} samples) | "
          f"Step: {step_samples} samples")

    while True:
        chunk, _timestamps = inlet.pull_chunk(timeout=0.1, max_samples=window_samples)
        if chunk:
            for sample in chunk:
                occipital_data = [sample[i] for i in OCCIPITAL_INDICES]
                data_buffer.append(occipital_data)

        if len(data_buffer) >= window_samples:
            # Trim buffer to the most recent window.
            data_buffer = data_buffer[-window_samples:]
            eeg_window  = np.array(data_buffer, dtype=np.float64)

            # Full preprocessing before CCA.
            eeg_clean = preprocess_eeg_window(eeg_window, bandpass_sos, notch_sos)

            best_freq, score = analyze_ssvep_window(eeg_clean, srate)

            if best_freq is not None:
                # Direct dict lookup — best_freq is already a key in FREQ_TO_COMMAND.
                cmd = FREQ_TO_COMMAND[best_freq]
                print(f"[EEG] Detected: {best_freq:>5.2f} Hz  "
                      f"(Score: {score:.3f})  →  {cmd.value}")
                active_eeg_cmd  = cmd
                active_eeg_time = time.time()

                # Advance by one step so the next window has fresh data.
                data_buffer = data_buffer[step_samples:]

        time.sleep(0.01)


# =============================================================================
# SECTION 9 — COMMAND EXECUTION & CALIBRATION VALUES
# =============================================================================

def _set_neutral_movement() -> None:
    """Return pitch and roll targets to hover-neutral (1500 µs)."""
    target_rc_channels["pitch"] = 1500.0
    target_rc_channels["roll"]  = 1500.0

def _disarm() -> None:
    """
    Emergency disarm — bypasses smoothing and writes directly to rc_channels
    so the drone stops immediately regardless of any pending targets.
    """
    rc_channels["throttle"]        = 1000.0
    target_rc_channels["throttle"] = 1000.0
    rc_channels["arm"]             = 1000

    _set_neutral_movement()
    # Also write directly so there is no interpolation lag on disarm.
    rc_channels["pitch"] = 1500.0
    rc_channels["roll"]  = 1500.0

def apply_command(command: Command) -> None:
    global is_moving, last_movement_time, drone_state

    vbat    = latest_telemetry["vbat"]
    vbat_str = f"[{vbat:.1f}V]" if vbat > 0 else "[No VBat]"

    # STOP is always processed, regardless of drone state.
    if command is Command.STOP:
        print(f"\n{vbat_str} [EMERGENCY STOP] Disarming immediately.")
        _disarm()
        is_moving   = False
        drone_state = DroneState.GROUNDED
        return

    if drone_state is DroneState.GROUNDED:
        if command is not Command.TAKEOFF:
            print(f"{vbat_str} [BLOCKED] Drone is grounded. "
                  f"Execute 'take off' first. (Ignored: {command.value})")
            return

        print(f"\n{vbat_str} [TAKEOFF] Arming and spooling up motors.")
        rc_channels["arm"] = 2000

        # ✏️ PASTE "throttle_hover" value from Calibration Script here:
        target_rc_channels["throttle"] = 1600.0

        drone_state = DroneState.AIRBORNE

    elif drone_state is DroneState.AIRBORNE:
        if command is Command.TAKEOFF:
            print("[IGNORED] Already airborne.")
            return

        if command is Command.LAND:
            print(f"\n{vbat_str} [LAND] Disarming and landing.")
            _disarm()
            is_moving   = False
            drone_state = DroneState.GROUNDED
            return

        print(f"{vbat_str} [MOVE] {command.value}")

        # ✏️ PASTE values from Calibration Script here:
        if command is Command.FORWARD:
            target_rc_channels["pitch"] = 1600.0
        elif command is Command.BACKWARD:
            target_rc_channels["pitch"] = 1400.0
        elif command is Command.LEFT:
            target_rc_channels["roll"]  = 1400.0
        elif command is Command.RIGHT:
            target_rc_channels["roll"]  = 1600.0

        last_movement_time = time.time()
        is_moving          = True


# =============================================================================
# SECTION 10 — MAIN CONTROL LOOP & TEST RUNNER BROADCAST
# =============================================================================

def main_control_loop() -> None:
    global active_voice_cmd, active_eeg_cmd, is_moving

    print(f"\n[Control Loop] Running in {EXPERIMENT_MODE.value} mode.")
    print(f"[Control Loop] Sending UDP to ESP32 at {ESP32_IP}:{ESP32_PORT}")
    print(f"[Control Loop] Forwarding Telemetry to Test Runner at {TEST_RUNNER_IP}:{TEST_RUNNER_PORT}")
    smooth_str = "ON" if ENABLE_SMOOTHING else "OFF (Instant)"
    print(f"[Control Loop] Movement smoothing: {smooth_str}")
    print("[State] Drone is GROUNDED and disarmed. Trigger TAKEOFF to begin.\n")

    while True:
        now = time.time()

        # STEP 1: Expire stale commands — prevents old detections from firing late.
        if now - active_voice_time > COMMAND_EXPIRY_SECONDS:
            active_voice_cmd = None
        if now - active_eeg_time > COMMAND_EXPIRY_SECONDS:
            active_eeg_cmd = None

        # STEP 2: Decide which command to execute based on experiment mode.
        final_cmd = None

        # STOP is a special case: either sensor alone can trigger an emergency stop.
        if active_voice_cmd is Command.STOP or active_eeg_cmd is Command.STOP:
            final_cmd        = Command.STOP
            active_voice_cmd = None
            active_eeg_cmd   = None

        elif EXPERIMENT_MODE is ExperimentMode.VOICE_ONLY:
            if active_voice_cmd:
                final_cmd        = active_voice_cmd
                active_voice_cmd = None

        elif EXPERIMENT_MODE is ExperimentMode.EEG_ONLY:
            if active_eeg_cmd:
                final_cmd      = active_eeg_cmd
                active_eeg_cmd = None

        elif EXPERIMENT_MODE is ExperimentMode.BOTH:
            # Fusion mode: both sensors must independently agree on the same
            # command before it is executed. This reduces false positives from
            # either channel acting alone.
            if active_voice_cmd and active_eeg_cmd:
                if active_voice_cmd is active_eeg_cmd:
                    print(f"[FUSION] Both sensors agree: {active_voice_cmd.value} → executing.")
                    final_cmd = active_voice_cmd
                else:
                    print(f"[FUSION] Sensors disagree — "
                          f"Voice: {active_voice_cmd.value} | "
                          f"EEG: {active_eeg_cmd.value} → ignoring.")

                active_voice_cmd = None
                active_eeg_cmd   = None

        # STEP 3: Apply the decided command (writes to target_rc_channels).
        if final_cmd:
            apply_command(final_cmd)

        # STEP 4: Auto-stop directional movement after ACTION_DURATION seconds.
        if is_moving and (now - last_movement_time > ACTION_DURATION):
            print("[AUTO-STOP] Returning to neutral hover.")
            _set_neutral_movement()
            is_moving = False

        # STEP 5: Interpolate actual RC values toward targets (smoothing).
        #         Emergency disarm bypasses this by writing rc_channels directly.
        for axis in ["roll", "pitch", "throttle", "yaw"]:
            if ENABLE_SMOOTHING:
                diff = target_rc_channels[axis] - rc_channels[axis]
                rc_channels[axis] += diff * SMOOTHING_FACTOR
            else:
                rc_channels[axis] = target_rc_channels[axis]

        # STEP 6: Transmit current channel values to the ESP32 over UDP.
        if EXPERIMENT_MODE is not ExperimentMode.PHYSICAL_RC:
            esp32_payload = (
                f"{int(rc_channels['roll'])},"
                f"{int(rc_channels['pitch'])},"
                f"{int(rc_channels['throttle'])},"
                f"{int(rc_channels['yaw'])},"
                f"{rc_channels['arm']}"
            )
            _udp_socket.sendto(esp32_payload.encode("utf-8"), (ESP32_IP, ESP32_PORT))

        # STEP 7: Broadcast Unified State to the Test Runner Script
        runner_payload = {
            "state": drone_state.value,
            "voice_cmd": active_voice_cmd.value if active_voice_cmd else None,
            "eeg_cmd": active_eeg_cmd.value if active_eeg_cmd else None,
            "final_cmd": final_cmd.value if final_cmd else None,
            "is_moving": is_moving,
            "eeg_score": latest_eeg_score,
            "rc_channels": rc_channels,          # What the script is sending to the drone
            "fc_telemetry": latest_telemetry     # Live data from the drone (Angles, Battery, Physical Sticks)
        }
        _test_runner_socket.sendto(json.dumps(runner_payload).encode("utf-8"), (TEST_RUNNER_IP, TEST_RUNNER_PORT))

        time.sleep(0.02)   # 50 Hz loop rate


# =============================================================================
# SECTION 11 — ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print(f"  Drone Ground Control — {EXPERIMENT_MODE.value} MODE")
    print(f"  Target: {ESP32_IP}:{ESP32_PORT}")
    print("=" * 60)

    threading.Thread(target=eeg_polling_thread,       daemon=True).start()
    threading.Thread(target=telemetry_listener_thread, daemon=True).start()

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
        print("\n[System] Ctrl+C received — shutting down.")
        _disarm()
        payload = (
            f"{int(rc_channels['roll'])},"
            f"{int(rc_channels['pitch'])},"
            f"{int(rc_channels['throttle'])},"
            f"{int(rc_channels['yaw'])},"
            f"{rc_channels['arm']}"
        )
        _udp_socket.sendto(payload.encode("utf-8"), (ESP32_IP, ESP32_PORT))
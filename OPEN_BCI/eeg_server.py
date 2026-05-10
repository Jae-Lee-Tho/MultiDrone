# server.py
import os
import time
import random
import numpy as np
from pynput import keyboard as pynput_keyboard
from pylsl import StreamInfo, StreamOutlet

# =============================================================
#  CONFIGURATION
# =============================================================
DATA_DIR      = "nakanishi_unfiltered_eeg/subject_8"
FS            = 256.0
CHUNK_SAMPLES = int(2.0 * FS)  # 512 samples = 2 seconds

# Updated to match the new frequency mapping in main_bci.py
COMMAND_MAPPING = {
    't': '9.25hz.npy',   # TAKEOFF
    'q': '10.25hz.npy',  # STOP
    'l': '11.25hz.npy',  # LAND
    'd': '12.75hz.npy',  # RIGHT
    'w': '13.75hz.npy',  # FORWARD
    's': '14.25hz.npy',  # BACKWARD
    'a': '14.75hz.npy',  # LEFT
}

# =============================================================
#  LOAD DATA
# =============================================================
print("=" * 60)
print("  MOCK EEG HEADSET — Subject 8 / Nakanishi SSVEP Dataset")
print("=" * 60)
print("\n[1/3] Loading Subject 8 trials into memory...")

eeg_data: dict[str, np.ndarray] = {}
for key, filename in COMMAND_MAPPING.items():
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  ERROR: Missing file → {path}")
        raise SystemExit(1)
    raw = np.load(path)
    eeg_data[key] = raw[:, 0:8, :]
    print(f"  ✓  '{key.upper()}' → {filename:<12} "
          f"({eeg_data[key].shape[0]:>2} trials, {eeg_data[key].shape[2]} samples each)")

# =============================================================
#  INIT LSL
# =============================================================
print("\n[2/3] Starting Lab Streaming Layer outlet...")
info   = StreamInfo('OpenBCI_Mock', 'EEG', 8, FS, 'float32', 'mock_uid_12345')
outlet = StreamOutlet(info)
print("  ✓  Stream 'OpenBCI_Mock' is live at 256 Hz, 8 channels")

# =============================================================
#  HELPERS
# =============================================================

def load_random_snippet(key: str) -> list[list[float]]:
    trials    = eeg_data[key]
    trial_idx = random.randint(0, trials.shape[0] - 1)
    max_start = trials.shape[2] - CHUNK_SAMPLES
    start_idx = random.randint(0, max(0, max_start))
    snippet   = trials[trial_idx, :, start_idx : start_idx + CHUNK_SAMPLES]
    return snippet.T.tolist()

SILENCE = [0.0] * 8  # flat zero sample — no signal, no noise

# =============================================================
#  KEYBOARD LISTENER (pynput — macOS-friendly, no sudo needed)
# =============================================================
pressed_keys: set[str] = set()
should_exit = False

def on_press(key):
    global should_exit
    if key == pynput_keyboard.Key.esc:
        should_exit = True
        return
    try:
        if hasattr(key, 'char') and key.char:
            pressed_keys.add(key.char.lower())
    except AttributeError:
        pass

def on_release(key):
    try:
        if hasattr(key, 'char') and key.char:
            pressed_keys.discard(key.char.lower())
    except AttributeError:
        pass

listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

# =============================================================
#  MAIN LOOP
# =============================================================
print("\n[3/3] Entering main streaming loop...\n")
print("-" * 60)
print("  Idle → streaming zeros (no signal)")
print("  Press keys to inject 2-second SSVEP bursts:\n")
print("    [T]      →  TAKEOFF   (9.25 Hz)")
print("    [Q]      →  STOP      (10.25 Hz)")
print("    [L]      →  LAND      (11.25 Hz)")
print("    [W]      →  FORWARD   (13.75 Hz)")
print("    [A]      →  LEFT      (14.75 Hz)")
print("    [S]      →  BACKWARD  (14.25 Hz)")
print("    [D]      →  RIGHT     (12.75 Hz)\n")
print("  [ESC]      →  Shut down server")
print("-" * 60 + "\n")

injection_buffer: list[list[float]] = []
next_sample_time = time.perf_counter()

try:
    while True:

        if should_exit:
            print("\n[SHUTDOWN] ESC pressed.")
            break

        # Inject on keypress, only when idle
        if not injection_buffer:
            for key, filename in COMMAND_MAPPING.items():
                if key in pressed_keys:
                    print(f"[INJECT]  '{key.upper()}' pressed → streaming {filename}")
                    injection_buffer = load_random_snippet(key)
                    time.sleep(0.20)  # debounce
                    break

        # Build sample
        if injection_buffer:
            sample = injection_buffer.pop(0)
            if not injection_buffer:
                print("[INJECT]  Burst complete — back to silence.\n")
        else:
            sample = SILENCE

        outlet.push_sample(sample)

        next_sample_time += 1.0 / FS
        drift = next_sample_time - time.perf_counter()
        if drift > 0:
            time.sleep(drift)
        else:
            next_sample_time = time.perf_counter()

except KeyboardInterrupt:
    print("\n[SHUTDOWN] Stopped.")
finally:
    listener.stop()
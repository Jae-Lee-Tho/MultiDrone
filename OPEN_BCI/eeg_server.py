# server.py
import os
import time
import random
import numpy as np
import keyboard
from pylsl import StreamInfo, StreamOutlet

# =============================================================
#  CONFIGURATION
# =============================================================
DATA_DIR      = "nakanishi_unfiltered_eeg/subject_8"
FS            = 256.0
CHUNK_SAMPLES = int(2.0 * FS)  # 512 samples = 2 seconds

COMMAND_MAPPING = {
    'w': '9.25hz.npy',
    's': '9.75hz.npy',
    'a': '10.25hz.npy',
    'd': '10.75hz.npy',
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
    print(f"  ✓  '{key}' → {filename}  "
          f"({eeg_data[key].shape[0]} trials, {eeg_data[key].shape[2]} samples each)")

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
#  MAIN LOOP
# =============================================================
print("\n[3/3] Entering main streaming loop...\n")
print("-" * 60)
print("  Idle → streaming zeros (no signal)")
print("  W / A / S / D  →  inject 2-second SSVEP burst")
print("  ESC            →  shut down")
print("-" * 60 + "\n")

injection_buffer: list[list[float]] = []
next_sample_time = time.perf_counter()

try:
    while True:

        if keyboard.is_pressed('esc'):
            print("\n[SHUTDOWN] ESC pressed.")
            break

        # Inject on keypress, only when idle
        if not injection_buffer:
            for key, filename in COMMAND_MAPPING.items():
                if keyboard.is_pressed(key):
                    print(f"[INJECT]  '{key.upper()}' → {filename}")
                    injection_buffer = load_random_snippet(key)
                    time.sleep(0.10)  # debounce
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
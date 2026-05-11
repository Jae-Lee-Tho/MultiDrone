# server.py
import os
import time
import random
import numpy as np
from pathlib import Path
from pynput import keyboard as pynput_keyboard
from pylsl import StreamInfo, StreamOutlet

# =============================================================
#  CONFIGURATION
# =============================================================
# Hardware-blind / OS-agnostic pathing using pathlib
DATA_DIR      = Path("nakanishi_unfiltered_eeg") / "subject_8"
FS            = 256.0
CHUNK_SAMPLES = int(2.0 * FS)  # 512 samples = 2 seconds

# Updated mapping with frequencies so the script can auto-generate mock data if missing
COMMAND_MAPPING = {
    't': ('9.25hz.npy', 9.25),   # TAKEOFF
    'q': ('10.25hz.npy', 10.25), # STOP
    'l': ('11.25hz.npy', 11.25), # LAND
    'd': ('12.75hz.npy', 12.75), # RIGHT
    'w': ('13.75hz.npy', 13.75), # FORWARD
    's': ('14.25hz.npy', 14.25), # BACKWARD
    'a': ('14.75hz.npy', 14.75), # LEFT
}

# =============================================================
#  CROSS-PLATFORM AUTO-SETUP ("Sort things out")
# =============================================================
def ensure_data_exists():
    """If the original datasets are missing, dynamically generate mathematical mock data."""
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    for key, (filename, freq) in COMMAND_MAPPING.items():
        path = DATA_DIR / filename
        if not path.exists():
            print(f"  [!] Missing {filename} -> Auto-generating mock SSVEP data ({freq}Hz)...")
            # Create mock data: 10 trials, 8 channels, 4 seconds of data
            trials, channels, samples = 10, 8, int(4.0 * FS)
            t = np.arange(samples) / FS

            # Generate a simulated SSVEP sine wave + white noise
            signal = np.sin(2 * np.pi * freq * t) * 10.0  # 10 uV amplitude
            mock_data = np.zeros((trials, channels, samples), dtype=np.float32)

            for tr in range(trials):
                for ch in range(channels):
                    noise = np.random.normal(0, 5.0, samples) # 5 uV noise
                    mock_data[tr, ch, :] = signal + noise

            np.save(path, mock_data)

def wait_until(target_time):
    """Cross-platform precision delay. Bypasses the Windows 15ms time.sleep() resolution bug."""
    while True:
        now = time.perf_counter()
        remaining = target_time - now
        if remaining <= 0:
            break
        # Sleep safely if we have plenty of time, spin-wait the final 15ms for microsecond accuracy
        if remaining > 0.016:
            time.sleep(0.001)
        else:
            pass

# =============================================================
#  LOAD DATA
# =============================================================
print("=" * 60)
print("  MOCK EEG HEADSET — Cross-Platform SSVEP Server")
print("=" * 60)
print("\n[1/3] Verifying and loading dataset...")

ensure_data_exists()

eeg_data: dict[str, np.ndarray] = {}
for key, (filename, _) in COMMAND_MAPPING.items():
    path = DATA_DIR / filename
    raw = np.load(path)
    eeg_data[key] = raw[:, 0:8, :]
    print(f"  ✓  '{key.upper()}' → {filename:<12} "
          f"({eeg_data[key].shape[0]:>2} trials, {eeg_data[key].shape[2]} samples each)")

# =============================================================
#  INIT LSL
# =============================================================
print("\n[2/3] Starting Lab Streaming Layer outlet...")
try:
    info   = StreamInfo('OpenBCI_Mock', 'EEG', 8, FS, 'float32', 'mock_uid_12345')
    outlet = StreamOutlet(info)
    print("  ✓  Stream 'OpenBCI_Mock' is live at 256 Hz, 8 channels")
except Exception as e:
    print(f"\n  [ERROR] LSL Initialization failed. Make sure 'pylsl' is installed. -> {e}")
    raise SystemExit(1)

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

SILENCE =[0.0] * 8

# =============================================================
#  KEYBOARD LISTENER
# =============================================================
pressed_keys: set[str] = set()
should_exit = False
listener = None

def on_press(key):
    global should_exit
    if key == pynput_keyboard.Key.esc:
        should_exit = True
        return False  # Stops listener safely
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

try:
    listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
except Exception as e:
    print(f"\n[WARNING] Global Keyboard Listener failed to start: {e}")
    print("This happens on headless Linux (no X11/Wayland) or macOS lacking Accessibility permissions.")
    print("Please fix permissions or use a graphical terminal. Exiting...")
    raise SystemExit(1)

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

injection_buffer: list[list[float]] =[]
next_sample_time = time.perf_counter()

try:
    while True:
        if should_exit:
            print("\n[SHUTDOWN] ESC pressed.")
            break

        # Inject on keypress, only when idle
        if not injection_buffer:
            for key, (filename, _) in COMMAND_MAPPING.items():
                if key in pressed_keys:
                    print(f"[INJECT]  '{key.upper()}' pressed → streaming {filename}")
                    injection_buffer = load_random_snippet(key)
                    time.sleep(0.20)  # debounce updated to match new logic
                    break

        # Build sample
        if injection_buffer:
            sample = injection_buffer.pop(0)
            if not injection_buffer:
                print("[INJECT]  Burst complete — back to silence.\n")
        else:
            sample = SILENCE

        outlet.push_sample(sample)

        # Precision hardware-blind timing
        next_sample_time += 1.0 / FS
        wait_until(next_sample_time)

        # If the OS slept the computer, reset clock so it doesn't try to rapidly catch up
        if time.perf_counter() > next_sample_time + 0.1:
            next_sample_time = time.perf_counter()

except KeyboardInterrupt:
    print("\n[SHUTDOWN] Stopped via Ctrl+C.")
finally:
    if listener:
        listener.stop()
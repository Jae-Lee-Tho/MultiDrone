# client.py
import time
import numpy as np
from pylsl import StreamInlet, resolve_byprop
from scipy import signal
from sklearn.cross_decomposition import CCA

# =============================================================
#  CONFIGURATION
# =============================================================
FS             = 256.0
WINDOW_SEC     = 2.0
WINDOW_SAMPLES = int(FS * WINDOW_SEC)
UPDATE_INTERVAL = int(FS * 0.25)   # run CCA 4× per second

CCA_THRESHOLD  = 0.5   # high — zeros make the noise floor ~0, so real signal stands out clearly
MARGIN_THRESHOLD = 0.20  # best freq must beat mean of all others by this much

TARGET_FREQS = [9.25, 9.75, 10.25, 10.75]

FREQ_TO_KEY = {
    9.25:  'W  (Takeoff/Forward)',
    9.75:  'S  (Land/Back)',
    10.25: 'A  (Turn Left)',
    10.75: 'D  (Turn Right)',
}

# =============================================================
#  PRE-COMPUTE TEMPLATES
# =============================================================
print("=" * 60)
print("  SSVEP BCI CLIENT — CCA Decoder")
print("=" * 60)
print("\n[1/3] Pre-computing sine/cosine reference templates...")

time_array = np.arange(WINDOW_SAMPLES) / FS
templates: dict[float, np.ndarray] = {}

for freq in TARGET_FREQS:
    refs = []
    for h in [1, 2, 3]:
        refs.append(np.sin(2 * np.pi * freq * h * time_array))
        refs.append(np.cos(2 * np.pi * freq * h * time_array))
    templates[freq] = np.array(refs).T  # (WINDOW_SAMPLES, 6)

# =============================================================
#  BANDPASS FILTER + CCA
# =============================================================
b, a = signal.butter(4, [6.0, 80.0], btype='bandpass', fs=FS)
cca  = CCA(n_components=1)

# =============================================================
#  CONNECT TO LSL
# =============================================================
print("\n[2/3] Looking for EEG stream on the network...")
streams = resolve_byprop('type', 'EEG', 1, 10.0)
if not streams:
    print("ERROR: No EEG stream found. Is the server running?")
    raise SystemExit(1)

inlet = StreamInlet(streams[0])
print("  ✓  Connected!\n")

# =============================================================
#  SILENCE DETECTOR
#  If the window is all zeros (or near-zero), the server is idle.
#  Skip CCA entirely — there is nothing to decode.
# =============================================================
SILENCE_THRESHOLD = 0.01  # µV — anything below this is treated as silence

# =============================================================
#  MAIN LOOP
# =============================================================
print("[3/3] Listening for commands...\n")
print("-" * 60)
print(f"  Thresholds → CCA ≥ {CCA_THRESHOLD}  |  Margin ≥ +{MARGIN_THRESHOLD}")
print("-" * 60 + "\n")

eeg_buffer: list[list[float]] = []
samples_since_last_cca = 0

try:
    while True:
        chunk, _ = inlet.pull_chunk(timeout=0.0, max_samples=WINDOW_SAMPLES)

        if not chunk:
            time.sleep(0.001)
            continue

        eeg_buffer.extend(chunk)
        samples_since_last_cca += len(chunk)

        if len(eeg_buffer) > WINDOW_SAMPLES:
            eeg_buffer = eeg_buffer[-WINDOW_SAMPLES:]

        if len(eeg_buffer) < WINDOW_SAMPLES:
            continue

        if samples_since_last_cca < UPDATE_INTERVAL:
            continue

        samples_since_last_cca = 0
        raw = np.array(eeg_buffer)  # (WINDOW_SAMPLES, 8)

        # ── Silence gate ─────────────────────────────────────────
        if np.max(np.abs(raw)) < SILENCE_THRESHOLD:
            # Server is idle — nothing to decode
            continue

        # ── Bandpass filter ──────────────────────────────────────
        filtered = signal.filtfilt(b, a, raw, axis=0)

        # ── CCA against all targets ──────────────────────────────
        scores: dict[float, float] = {}
        for freq, Y in templates.items():
            X_c, Y_c = cca.fit_transform(filtered, Y)
            scores[freq] = float(np.corrcoef(X_c[:, 0], Y_c[:, 0])[0, 1])

        best_freq  = max(scores, key=scores.get)
        best_score = scores[best_freq]
        noise_floor = np.mean([s for f, s in scores.items() if f != best_freq])
        margin      = best_score - noise_floor

        # ── Decision ─────────────────────────────────────────────
        if best_score >= CCA_THRESHOLD and margin >= MARGIN_THRESHOLD:
            ts  = time.strftime('%H:%M:%S')
            cmd = FREQ_TO_KEY.get(best_freq, '???')
            print(f"[{ts}]  ⚡ {cmd:<24}  {best_freq:.2f} Hz  "
                  f"score={best_score:.3f}  margin=+{margin:.3f}")
            eeg_buffer = []  # clear to avoid re-triggering on same burst

except KeyboardInterrupt:
    print("\n[SHUTDOWN] Client stopped.")
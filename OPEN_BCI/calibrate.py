import numpy as np
from pylsl import resolve_byprop, StreamInlet
from scipy.signal import butter, filtfilt, iirnotch, welch
from sklearn.cross_decomposition import CCA

# --- CONFIGURATION ---
WINDOW_SECONDS    = 2.0
OCCIPITAL_INDICES = [5, 7]
CALIBRATION_TARGET_HZ = 60 / 4   # 15.0 Hz

# --- PREPROCESSING PARAMETERS ---
BANDPASS_LOW_HZ   = 3.0
BANDPASS_HIGH_HZ  = 60.0
NOTCH_HZ          = 60.0
NOTCH_Q           = 30.0
BANDPASS_ORDER    = 4


# ---------------------------------------------------------------------------
# PREPROCESSING HELPERS
# ---------------------------------------------------------------------------

def make_filters(srate: float):
    nyq = srate / 2.0
    b_bp, a_bp = butter(BANDPASS_ORDER,[BANDPASS_LOW_HZ / nyq, BANDPASS_HIGH_HZ / nyq], btype='bandpass')
    b_notch, a_notch = iirnotch(NOTCH_HZ / nyq, NOTCH_Q)
    return (b_bp, a_bp), (b_notch, a_notch)


def preprocess(data: np.ndarray, filters, srate: float, apply_gate: bool = False) -> np.ndarray:
    """
    Filters the data.
    If apply_gate is True, it will zero out the array if a >200uV spike is found.
    (We only want apply_gate=True during 2-second sliding windows, NOT 10s blocks!)
    """
    (b_bp, a_bp), (b_notch, a_notch) = filters

    # 1. Bandpass
    data = filtfilt(b_bp, a_bp, data, axis=0)

    # 2. Notch filter
    data = filtfilt(b_notch, a_notch, data, axis=0)

    # [REMOVED CAR] - Doing CAR on only 2 channels causes them to mirror each other.

    # 3. Amplitude gate
    if apply_gate:
        peak_to_peak = data.max(axis=0) - data.min(axis=0)
        bad_channels = peak_to_peak > 200
        if bad_channels.any():
            print(f"      -> [GATE TRIGGERED] Spike detected > 200uV (P2P: {peak_to_peak.astype(int)}). Zeroing window.")
            data[:, bad_channels] = 0.0

    return data


def channel_quality_report(data: np.ndarray, label: str = ""):
    print(f"\n  {'Ch':>4}  {'Mean uV':>9}  {'Std uV':>8}  {'P2P uV':>8}  {'Status'}")
    print("  " + "-" * 50)
    for i in range(data.shape[1]):
        ch      = OCCIPITAL_INDICES[i]
        mean_uv = data[:, i].mean()
        std_uv  = data[:, i].std()
        p2p     = data[:, i].max() - data[:, i].min()

        if std_uv < 1e-6:
            status = "BAD  FLAT"
        elif p2p > 200:
            status = "WARNING  ARTEFACT (>200uV p2p)"
        elif std_uv > 100:
            status = "WARNING  NOISY"
        else:
            status = "OK"

        print(f"  {ch:>4}  {mean_uv:>9.2f}  {std_uv:>8.2f}  {p2p:>8.1f}  {status}")
    print()


def check_snr(data: np.ndarray, srate: float, target_hz: float) -> float:
    snrs = []
    print(f"[SNR Breakdown @ {target_hz} Hz]")
    for ch in range(data.shape[1]):
        freqs, psd = welch(data[:, ch], fs=srate, nperseg=int(srate * 2))
        sig_mask   = (freqs >= target_hz - 0.5) & (freqs <= target_hz + 0.5)
        noise_mask = ((freqs >= target_hz - 3.0) & (freqs < target_hz - 0.5)) | \
                     ((freqs > target_hz + 0.5) & (freqs <= target_hz + 3.0))

        if sig_mask.any() and noise_mask.any():
            sig_power   = max(psd[sig_mask].mean(), 1e-12)
            noise_power = max(psd[noise_mask].mean(), 1e-12)
            snr_db      = 10 * np.log10(sig_power / noise_power)
            snrs.append(snr_db)
            print(f"    Ch {OCCIPITAL_INDICES[ch]:>2} | Sig Pwr: {sig_power:>6.2f} | Noise Pwr: {noise_power:>6.2f} | SNR: {snr_db:>+5.1f} dB")

    return float(np.mean(snrs)) if snrs else 0.0


# ---------------------------------------------------------------------------
# REFERENCE SIGNAL & SCORING
# ---------------------------------------------------------------------------

def generate_reference_signals(length: int, sample_rate: float,
                                target_freq: float, num_harmonics: int = 3) -> np.ndarray:
    t     = np.arange(0, length) / sample_rate
    y_ref =[]
    for i in range(1, num_harmonics + 1):
        y_ref.append(np.sin(2 * np.pi * i * target_freq * t))
        y_ref.append(np.cos(2 * np.pi * i * target_freq * t))
    return np.array(y_ref).T


def score_calibration_block(data_block: np.ndarray, srate: float,
                             target_freq: float, filters, phase_name: str) -> list:
    window_samples = int(WINDOW_SECONDS * srate)
    step_size      = int(srate * 0.5)
    scores         =[]

    print(f"\n  [Sliding Window Analysis: {phase_name}]")
    window_count = 0

    for i in range(0, len(data_block) - window_samples, step_size):
        window_count += 1
        window = data_block[i: i + window_samples].copy()

        # apply_gate=True so blinks only ruin this specific 2-second window!
        window = preprocess(window, filters, srate, apply_gate=True)

        if window.max() - window.min() < 1e-6:
            print(f"    Window {window_count:>2} : SKIPPED (Discarded by artefact gate)")
            continue

        y_ref    = generate_reference_signals(window_samples, srate, target_freq)
        cca      = CCA(n_components=1)
        cca.fit(window, y_ref)
        X_c, Y_c = cca.transform(window, y_ref)
        score    = np.corrcoef(X_c[:, 0], Y_c[:, 0])[0, 1]
        scores.append(score)
        print(f"    Window {window_count:>2} : CCA Score = {score:.3f}")

    return scores


# ---------------------------------------------------------------------------
# DATA COLLECTION
# ---------------------------------------------------------------------------

def collect_data(inlet, duration_sec: float, srate: float) -> np.ndarray:
    samples_needed = int(duration_sec * srate)
    data           =[]
    print(f"  Recording for {duration_sec:.0f} seconds...")
    while len(data) < samples_needed:
        sample, _ = inlet.pull_sample()
        data.append([sample[i] for i in OCCIPITAL_INDICES])
    print("  Recording complete!\n")
    return np.array(data)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 65)
    print("  OpenBCI SSVEP Calibration Tool (Verbose Mode)")
    print("=" * 65)

    print("\nLooking for an EEG LSL stream...")
    streams = resolve_byprop('type', 'EEG', timeout=10.0)
    if not streams:
        print("ERROR: No EEG stream found. Ensure LSL is streaming via TimeSeries.")
        return

    inlet = StreamInlet(streams[0])
    info  = inlet.info()
    srate = info.nominal_srate() or 250.0

    print(f"Connected to '{info.name()}' | Srate: {srate:.1f}Hz | Target: {CALIBRATION_TARGET_HZ:.1f}Hz")
    filters = make_filters(srate)

    print("\n" + "=" * 65)

    # -- PHASE 1: NOISE FLOOR --------------------------------------------------
    print("\n[PHASE 1: NOISE FLOOR]")
    print("  Subject: look at a blank wall and stay still.")
    input("  Press ENTER when ready...")
    idle_raw = collect_data(inlet, 10, srate)

    # Preprocess with apply_gate=False so we can see actual P2P stats of the block
    idle_filtered = preprocess(idle_raw.copy(), filters, srate, apply_gate=False)

    print("  Filtered channel quality (10s block):")
    channel_quality_report(idle_filtered, "idle")

    idle_snr = check_snr(idle_filtered, srate, CALIBRATION_TARGET_HZ)
    print(f"  Average Idle SNR: {idle_snr:+.1f} dB")

    # -- PHASE 2: ACTIVE SIGNAL ------------------------------------------------
    print("\n" + "=" * 65)
    print("\n[PHASE 2: ACTIVE SIGNAL]")
    print(f"  Start flashing your {CALIBRATION_TARGET_HZ:.1f} Hz stimulus.")
    print("  Subject: stare directly at the centre without blinking.")
    input("  Press ENTER when subject is fixating...")
    active_raw = collect_data(inlet, 10, srate)

    # Preprocess with apply_gate=False so we can see actual P2P stats of the block
    active_filtered = preprocess(active_raw.copy(), filters, srate, apply_gate=False)

    print("  Filtered channel quality (10s block):")
    channel_quality_report(active_filtered, "active")

    active_snr = check_snr(active_filtered, srate, CALIBRATION_TARGET_HZ)
    print(f"  Average Active SNR: {active_snr:+.1f} dB")

    # -- PHASE 3: CCA SCORING & THRESHOLD --------------------------------------
    print("\n" + "=" * 65)
    print("\n[PHASE 3: CALCULATING THRESHOLD...]")

    idle_scores   = score_calibration_block(idle_raw,   srate, CALIBRATION_TARGET_HZ, filters, "IDLE")
    active_scores = score_calibration_block(active_raw, srate, CALIBRATION_TARGET_HZ, filters, "ACTIVE")

    if not idle_scores or not active_scores:
        print("\nERROR: Not enough clean windows to score. Too many artifacts.")
        return

    max_idle   = np.max(idle_scores)
    avg_active = np.mean(active_scores)
    min_active = np.min(active_scores)

    print(f"\n[FINAL RESULTS]")
    print(f"  Idle   scores  ->  max={max_idle:.3f}  mean={np.mean(idle_scores):.3f}  std={np.std(idle_scores):.3f}")
    print(f"  Active scores  ->  min={min_active:.3f}  mean={avg_active:.3f}  std={np.std(active_scores):.3f}")

    print("\n" + "=" * 65)
    if max_idle >= avg_active:
        print("WARNING: Noise floor >= active signal!")
        print("    - Re-seat occipital electrodes directly on skin (part hair)")
        print("    - Increase stimulus brightness / contrast")
        print("    - If using an LCD monitor, ensure it can perfectly render 15.0Hz")
        print("      (e.g., a 60Hz monitor flashing exactly every 4 frames)")
    else:
        recommended = max_idle + (avg_active - max_idle) / 2
        separation  = avg_active - max_idle
        print(f"RECOMMENDED CONFIDENCE_THRESHOLD : {recommended:.3f}")
        print(f"    Signal separation (active - noise): {separation:.3f}")
        print("=" * 65)


if __name__ == '__main__':
    main()
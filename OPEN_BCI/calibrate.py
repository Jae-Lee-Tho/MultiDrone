import time
import numpy as np
from pylsl import resolve_byprop, StreamInlet
from sklearn.cross_decomposition import CCA

# --- CONFIGURATION ---
WINDOW_SECONDS = 2.0
OCCIPITAL_INDICES = [5, 6, 7]
CALIBRATION_TARGET_HZ = 60/4 # 15.0 Hz (Pick whichever frequency you want to test with)

def generate_reference_signals(length, sample_rate, target_freq, num_harmonics=3):
    t = np.arange(0, length) / sample_rate
    y_ref = []
    for i in range(1, num_harmonics + 1):
        y_ref.append(np.sin(2 * np.pi * i * target_freq * t))
        y_ref.append(np.cos(2 * np.pi * i * target_freq * t))
    return np.array(y_ref).T

def collect_data(inlet, duration_sec, srate):
    """Records a continuous block of EEG data."""
    samples_needed = int(duration_sec * srate)
    data = []

    print(f"🔴 Recording for {duration_sec} seconds...")
    while len(data) < samples_needed:
        sample, _ = inlet.pull_sample()
        occipital_data = [sample[i] for i in OCCIPITAL_INDICES]
        data.append(occipital_data)

    print("✅ Recording complete!\n")
    return np.array(data)

def score_calibration_block(data_block, srate, target_freq):
    """Slices the recorded data into 2-second windows and scores each one."""
    window_samples = int(WINDOW_SECONDS * srate)
    step_size = int(srate * 0.5) # Slide the window forward by 0.5 seconds
    scores = []

    # Slide our window across the recorded data block
    for i in range(0, len(data_block) - window_samples, step_size):
        window = data_block[i : i + window_samples]

        y_ref = generate_reference_signals(window_samples, srate, target_freq)
        cca = CCA(n_components=1)
        cca.fit(window, y_ref)
        X_c, Y_c = cca.transform(window, y_ref)
        score = np.corrcoef(X_c[:, 0], Y_c[:, 0])[0, 1]

        scores.append(score)

    return scores

def main():
    print("Looking for the OpenBCI stream...")
    streams = resolve_byprop('type', 'EEG', timeout=5.0)

    if not streams:
        print("Error: Could not find the stream. Is OpenBCI GUI running?")
        return

    inlet = StreamInlet(streams[0])
    srate = inlet.info().nominal_srate() or 250.0

    print(f"Connected! Sample rate: {srate}Hz")
    print("=" * 50)

    # --- STEP 1: RECORD IDLE NOISE ---
    print("\n[PHASE 1: THE NOISE FLOOR]")
    print("Instructions: Have the user look at a blank wall and relax.")
    input("Press ENTER when the user is ready...")

    idle_data = collect_data(inlet, 10, srate)

    # --- STEP 2: RECORD ACTIVE SIGNAL ---
    print("\n[PHASE 2: THE SIGNAL PEAK]")
    print(f"Instructions: Start flashing your {CALIBRATION_TARGET_HZ}Hz target on the monitor.")
    print("Have the user stare directly at it without blinking.")
    input("Press ENTER when the user is staring at the target...")

    active_data = collect_data(inlet, 10, srate)

    # --- STEP 3: ANALYZE AND CALCULATE ---
    print("\n[PHASE 3: CALCULATING THRESHOLD...]")

    idle_scores = score_calibration_block(idle_data, srate, CALIBRATION_TARGET_HZ)
    active_scores = score_calibration_block(active_data, srate, CALIBRATION_TARGET_HZ)

    max_idle = np.max(idle_scores)
    avg_active = np.mean(active_scores)

    print(f"-> Highest Noise Score (Idling): {max_idle:.3f}")
    print(f"-> Average Signal Score (Active): {avg_active:.3f}")

    if max_idle >= avg_active:
        print("\n❌ WARNING: Your noise floor is higher than your signal!")
        print("The sensors on the back of the head might be loose, or the flashing light isn't bright enough.")
    else:
        # The optimal threshold is exactly halfway between their highest noise and their average signal
        recommended_threshold = max_idle + ((avg_active - max_idle) / 2)
        print("\n" + "=" * 50)
        print(f"🎯 RECOMMENDED CONFIDENCE_THRESHOLD: {recommended_threshold:.3f}")
        print("=" * 50)
        print("Copy this number into your main_bci.py configuration!")

if __name__ == '__main__':
    main()
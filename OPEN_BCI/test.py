import numpy as np
from pylsl import resolve_byprop, StreamInlet
from sklearn.cross_decomposition import CCA

# --- CONFIGURATION ---
# The exact frequencies flashing on the 60Hz monitor
TARGET_FREQS = [60/3, 60/4, 60/5, 60/8, 60/9, 60/10, 60/12]
WINDOW_SECONDS = 2.0

# Which array indices correspond to the sensors on the back of the head?
# (In Python, 5, 6, 7 means the 6th, 7th, and 8th sensors on the board)
OCCIPITAL_INDICES = [5, 6, 7]


def generate_reference_signals(length, sample_rate, target_freq, num_harmonics=3):
    t = np.arange(0, length) / sample_rate
    y_ref = []
    for i in range(1, num_harmonics + 1):
        y_ref.append(np.sin(2 * np.pi * i * target_freq * t))
        y_ref.append(np.cos(2 * np.pi * i * target_freq * t))
    return np.array(y_ref).T

def analyze_ssvep_window(eeg_data, sample_rate):
    samples = eeg_data.shape[0]
    best_freq = None
    highest_score = 0

    for freq in TARGET_FREQS:
        y_ref = generate_reference_signals(samples, sample_rate, freq)
        cca = CCA(n_components=1)
        cca.fit(eeg_data, y_ref)
        X_c, Y_c = cca.transform(eeg_data, y_ref)
        score = np.corrcoef(X_c[:, 0], Y_c[:, 0])[0, 1]

        if score > highest_score:
            highest_score = score
            best_freq = freq

    return best_freq, highest_score

def main():
    print("Looking for an EEG stream on the local network...")

    # NEW: resolve_byprop with a 5-second timeout
    streams = resolve_byprop('type', 'EEG', timeout=5.0)

    # NEW: Graceful exit if the stream isn't broadcasting
    if not streams:
        print("\nError: Could not find the OpenBCI stream!")
        print("Please ensure the OpenBCI GUI is running and the LSL Networking widget is active.")
        return

    inlet = StreamInlet(streams[0])

    # Dynamically grab the hardware's sample rate
    srate = inlet.info().nominal_srate()
    if srate <= 0.0:
        srate = 250.0 # Fallback if metadata is missing

    window_size = int(srate * WINDOW_SECONDS)
    data_buffer = []

    print(f"Connected! Buffering {WINDOW_SECONDS} seconds of data at {srate}Hz...")
    print("-" * 50)

    try:
        while True:
            # 1. Pull the data from the network
            sample, _timestamp = inlet.pull_sample(timeout=1.0)
            if sample is None:
                continue

            # 2. Slice out ONLY the occipital sensors and add to our buffer
            occipital_data = [sample[i] for i in OCCIPITAL_INDICES if i < len(sample)]
            if len(occipital_data) != len(OCCIPITAL_INDICES):
                continue
            data_buffer.append(occipital_data)

            # 3. Once we have exactly 2 seconds of data, run the algorithm
            if len(data_buffer) >= window_size:
                eeg_window = np.array(data_buffer)

                # Analyze it
                best_freq, score = analyze_ssvep_window(eeg_window, srate)

                # Format the output so we can read it easily
                print(f"Detected: [{best_freq:>5.2f} Hz] | Confidence Score: {score:.3f}")

                # 4. Clear the buffer to start gathering the next 2 seconds
                data_buffer = []

    except KeyboardInterrupt:
        print("\nDisconnected from stream.")

if __name__ == '__main__':
    main()
import time
import numpy as np
from pylsl import StreamInfo, StreamOutlet, cf_float32

def run_mock_server():
    # 1. Setup the fake stream parameters (Matches OpenBCI Cyton)
    num_channels = 8
    sample_rate = 250
    target_frequency = 10.0 # We will inject a 10Hz signal for the client to find

    info = StreamInfo('OpenBCI_GUI', 'EEG', num_channels, sample_rate, cf_float32, 'mock_uid_123')
    outlet = StreamOutlet(info)

    print("Mock OpenBCI Server running...")
    print(f"Broadcasting {num_channels} channels at {sample_rate}Hz over LSL.")
    print(f"Injecting a hidden {target_frequency}Hz signal into Occipital channels.")
    print("Press Ctrl+C to stop.")

    start_time = time.time()

    try:
        while True:
            # Calculate current time for the sine wave
            t = time.time() - start_time

            # Generate a baseline of random electrical noise for all 8 sensors
            sample = np.random.normal(loc=0.0, scale=0.5, size=num_channels)

            # Inject our 10Hz "brainwave" into the Occipital sensors
            # Let's pretend channels 5, 6, and 7 are our O1, O2, Oz sensors
            ssvep_signal = np.sin(2 * np.pi * target_frequency * t)

            sample[5] += ssvep_signal * 1.2 # slightly stronger
            sample[6] += ssvep_signal * 0.8 # slightly weaker
            sample[7] += ssvep_signal * 1.0 # normal

            # Broadcast the array over the local network
            outlet.push_sample(sample.tolist())

            # Sleep to maintain the 250Hz sample rate
            time.sleep(1.0 / sample_rate)

    except KeyboardInterrupt:
        print("\nMock server shut down.")

if __name__ == '__main__':
    run_mock_server()
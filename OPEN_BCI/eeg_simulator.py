import time
import csv
import argparse
from pylsl import StreamInlet, resolve_byprop, StreamInfo, StreamOutlet

def record_eeg(filename: str):
    print("========================================")
    print("   EEG LSL RECORDER (Lab Mode)")
    print("========================================")
    print("[1/2] Looking for OpenBCI LSL stream...")

    streams = resolve_byprop('type', 'EEG', timeout=10.0)
    if not streams:
        print("[Error] No EEG stream found! Is the OpenBCI GUI broadcasting?")
        return

    inlet = StreamInlet(streams[0])
    srate = inlet.info().nominal_srate() or 250.0
    channels = inlet.info().channel_count()

    print(f"[2/2] Connected! Channels: {channels} | Sample Rate: {srate} Hz")
    print(f"\n🔴 RECORDING LIVE TO: {filename}")
    print("Press Ctrl+C to stop recording...\n")

    try:
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write Header: timestamp, ch0, ch1, ch2...
            header = ["timestamp"] + [f"ch{i}" for i in range(channels)]
            writer.writerow(header)

            start_time = time.time()
            sample_count = 0

            while True:
                chunk, timestamps = inlet.pull_chunk(timeout=1.0)
                if chunk:
                    for i in range(len(chunk)):
                        # Save LSL timestamp + all channel data
                        row = [timestamps[i]] + chunk[i]
                        writer.writerow(row)
                        sample_count += 1

                # Print live status update every ~1 second
                if time.time() - start_time > 1.0:
                    print(f"Recorded {sample_count} samples...", end='\r')
                    start_time = time.time()

    except KeyboardInterrupt:
        print(f"\n\n[Done] Successfully saved {sample_count} samples to {filename}")

def play_eeg(filename: str):
    print("========================================")
    print("   EEG LSL SIMULATOR (Field Mode)")
    print("========================================")
    print(f"[1/3] Loading recorded data from {filename}...")

    try:
        with open(filename, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)

            data =[]
            for row in reader:
                # First column is timestamp, the rest are float values
                data.append([float(val) for val in row[1:]])
    except FileNotFoundError:
        print(f"[Error] Could not find file: {filename}")
        return

    channels = len(data[0])
    srate = 250.0  # Default OpenBCI Cyton rate

    print(f"[2/3] Loaded {len(data)} samples. (Channels: {channels}, Target Rate: {srate} Hz)")
    print("[3/3] Broadcasting simulated LSL Stream...")

    # Create the fake stream
    info = StreamInfo(name='OpenBCI_Simulated', type='EEG',
                      channel_count=channels, nominal_srate=srate,
                      channel_format='float32', source_id='sim_eeg_123')
    outlet = StreamOutlet(info)

    print("\n▶️  STREAMING LIVE! (Start main_bci.py now)")
    print("Press Ctrl+C to stop...\n")

    # Timing variables to ensure accurate playback speed without drift
    interval = 1.0 / srate
    start_time = time.time()

    try:
        for i, sample in enumerate(data):
            # Calculate exactly when this sample *should* be played
            target_time = start_time + (i * interval)
            now = time.time()

            # If we are ahead of schedule, sleep to wait for the exact moment
            if now < target_time:
                time.sleep(target_time - now)

            # Broadcast the sample to the network
            outlet.push_sample(sample)

            if i % int(srate) == 0:
                print(f"Streaming time elapsed: {int(i / srate)} seconds", end='\r')

        print("\n\n[Done] Reached end of recorded file.")

    except KeyboardInterrupt:
        print("\n\n[Stopped] Playback interrupted by user.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record or Simulate OpenBCI LSL Streams")
    parser.add_argument("mode", choices=["record", "play"], help="Choose whether to record a new file or play an existing one")
    parser.add_argument("--file", "-f", default="lab_eeg_data.csv", help="Filename to save to or read from")

    args = parser.parse_args()

    if args.mode == "record":
        record_eeg(args.file)
    else:
        play_eeg(args.file)
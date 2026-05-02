import csv
import time
import sys
from datetime import datetime
from pylsl import resolve_byprop, StreamInlet

# --- PERFECT 60Hz MONITOR FREQUENCIES ---
# Format: (Frequency in Hz, Number of Frames per cycle)
TARGET_FREQUENCIES =[
    ("IDLE", "Baseline (Blank Wall)"),
    (6.00, "10 frames"),
    (6.66, "9 frames"),
    (7.50, "8 frames"),
    (8.57, "7 frames"),
    (10.0, "6 frames"),
    (12.0, "5 frames"),
    (15.0, "4 frames"),
    (20.0, "3 frames"),
    (30.0, "2 frames")
]

def record_block(inlet, num_channels, srate, freq_val, description):
    """Records data continuously to a specific file until Ctrl+C is pressed."""

    # 1. Format filename based on whether it's IDLE or a specific Hz
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if freq_val == "IDLE":
        filename = f"raw_IDLE_baseline_{timestamp}.csv"
        display_name = "IDLE (Baseline)"
    else:
        filename = f"raw_{freq_val}Hz_{description.replace(' ', '')}_{timestamp}.csv"
        display_name = f"{freq_val} Hz"

    print("\n" + "=" * 60)
    print(f"  NEXT UP: {display_name}  [{description}]")
    print("=" * 60)

    # Allow user to setup the stimulus, then start
    user_input = input("  Press ENTER to begin recording (or type 'skip' to skip, 'q' to quit): ").strip().lower()

    if user_input == 'q':
        print("\nExiting sequence. Goodbye!")
        sys.exit(0)
    elif user_input == 'skip':
        print(f"  -> Skipping {display_name}...")
        return

    # 2. CLEAR THE BUFFER!
    # Throw away old data that piled up while waiting at the prompt/break
    inlet.pull_chunk()

    print(f"\n  [RECORDING] Saving to: {filename}")
    print("  [ACTION]    Press Ctrl+C to STOP recording and move to the break.\n")

    # 3. Open file and start the loop
    with open(filename, mode='w', newline='') as csv_file:
        csv_writer = csv.writer(csv_file)

        # Header row
        header = ['System_Time', 'LSL_Timestamp'] +[f'Channel_{i}' for i in range(num_channels)]
        csv_writer.writerow(header)

        samples_recorded = 0
        start_time = time.time()

        try:
            while True:
                sample, lsl_timestamp = inlet.pull_sample()
                system_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]

                csv_writer.writerow([system_time, lsl_timestamp] + sample)
                samples_recorded += 1

                # Print status update every 1 second
                if samples_recorded % int(srate) == 0:
                    elapsed = time.time() - start_time
                    print(f"    Recording... {elapsed:.0f}s elapsed ({samples_recorded} samples)", end='\r')

        except KeyboardInterrupt:
            # Ctrl+C safely breaks the loop and closes the file, returning to main()
            elapsed = time.time() - start_time
            print(f"\n\n  -> [STOPPED] Saved {elapsed:.1f} seconds to {filename}")
            time.sleep(1) # Brief pause


def main():
    print("=" * 60)
    print("  OpenBCI 60Hz SSVEP Calibration Sweep")
    print("=" * 60)
    print("\nLooking for an EEG LSL stream...")

    streams = resolve_byprop('type', 'EEG', timeout=10.0)
    if not streams:
        print("ERROR: No EEG stream found. Ensure OpenBCI is streaming via LSL.")
        return

    inlet = StreamInlet(streams[0])
    info  = inlet.info()
    num_channels = info.channel_count()
    srate = info.nominal_srate() or 250.0

    print(f"Connected to '{info.name()}' | Channels: {num_channels} | SRate: {srate} Hz")

    # Sequentially walk through the frequencies
    total_steps = len(TARGET_FREQUENCIES)
    for i, (freq_val, description) in enumerate(TARGET_FREQUENCIES):

        # Run the recording for this frequency
        record_block(inlet, num_channels, srate, freq_val, description)

        # If there are more frequencies left in the list, trigger the break phase
        if i < total_steps - 1:
            print("\n" + "~" * 60)
            print("  *** REST PERIOD ***")
            print("  Tell the subject to blink, swallow, and let their jaw relax.")
            input("  -> Press ENTER when rested and ready to setup the next stimulus...")
            print("~" * 60)

    print("\n" + "=" * 60)
    print("  SEQUENCE COMPLETE! All frequencies recorded.")
    print("=" * 60)

if __name__ == '__main__':
    main()
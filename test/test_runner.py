import socket
import json
import time
import csv
import os
import threading
from datetime import datetime

TELEMETRY_IP = "0.0.0.0"
TELEMETRY_PORT = 4211  # We only need this port now! The main script forwards everything here.

recording = True

def load_sequences():
    # Fallback sequences in case the JSON isn't found
    try:
        with open('test_sequences.json', 'r') as f:
            return json.load(f)["tests"]
    except FileNotFoundError:
        return [
            {"name": "Level 1 - Easy", "sequence": ["FORWARD", "BACKWARD"]},
            {"name": "Level 2 - Medium", "sequence": ["LEFT", "LEFT", "RIGHT", "RIGHT"]},
            {"name": "Level 3 - Hard", "sequence":["FORWARD", "LEFT", "RIGHT", "BACKWARD"]}
        ]

def end_test_monitor():
    global recording
    input("\n[PRESS ENTER TO END THE TEST AND SAVE DATA]\n")
    recording = False

def main():
    global recording
    print("========================================")
    print("   DRONE METHOD COMPARISON TEST RUNNER")
    print("========================================")

    # Select method (Fixed EMG -> EEG)
    methods =["VOICE_ONLY", "EEG_ONLY", "VOICE_AND_EEG", "PHYSICAL_CONTROLLER"]
    print("\nSelect the control method you are testing:")
    for i, m in enumerate(methods):
        print(f"  {i+1}. {m}")
    method_idx = int(input("Choice (1-4): ")) - 1
    selected_method = methods[method_idx]

    # Select sequence
    sequences = load_sequences()
    print("\nSelect the test sequence:")
    for i, seq in enumerate(sequences):
        print(f"  {i+1}. {seq['name']} -> {seq['sequence']}")
    seq_idx = int(input(f"Choice (1-{len(sequences)}): ")) - 1
    selected_test = sequences[seq_idx]

    # Setup UDP socket (Only listening to the Python Main BCI Script)
    main_script_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    main_script_sock.bind((TELEMETRY_IP, TELEMETRY_PORT))
    main_script_sock.setblocking(False)

    # Setup CSV logging
    os.makedirs('results', exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"results/{selected_method}_{selected_test['name'].replace(' ', '_')}_{timestamp_str}.csv"

    csv_file = open(filename, 'w', newline='')
    writer = csv.writer(csv_file)

    # NEW HEADERS: Added eeg_score, physical_rc, and test elapsed time!
    writer.writerow([
        "system_time", "test_elapsed_sec", "test_method", "test_name",
        "drone_state", "voice_cmd", "eeg_cmd", "final_cmd", "eeg_score",
        "is_moving",
        "bci_target_roll", "bci_target_pitch", "bci_target_throttle",
        "phys_rc_roll", "phys_rc_pitch", "phys_rc_throttle",
        "fc_roll_angle", "fc_pitch_angle", "fc_yaw_angle", "fc_voltage"
    ])

    print(f"\n[Ready] Logging data to: {filename}")
    print("[Ready] Ensure your Main BCI Script is running!")

    print("\n==================================================")
    print(f" GOAL SEQUENCE: {selected_test['sequence']}")
    print("==================================================")
    print("The test is NOW RECORDING telemetry in the background.")
    print("Perform Take Off, the full sequence, and Land.")
    print("Press ENTER at any time to finish the test and save the data.")
    print("==================================================\n")

    threading.Thread(target=end_test_monitor, daemon=True).start()

    start_time = time.time()
    commands_executed =[]

    try:
        while recording:
            try:
                # Receive unified payload from the Main BCI script
                data, _ = main_script_sock.recvfrom(4096)
                telem = json.loads(data.decode('utf-8'))
                current_time = time.time()
                elapsed_sec = current_time - start_time

                # Track commands for the summary
                if telem.get("final_cmd") and (len(commands_executed) == 0 or commands_executed[-1] != telem["final_cmd"]):
                    commands_executed.append(telem["final_cmd"])
                    print(f"[{elapsed_sec:.1f}s] -> Executed: {telem['final_cmd']}")

                bci_rc = telem.get("rc_channels", {})
                fc_telem = telem.get("fc_telemetry", {})

                writer.writerow([
                    current_time,
                    round(elapsed_sec, 3),
                    selected_method,
                    selected_test["name"],
                    telem.get("state"),
                    telem.get("voice_cmd"),
                    telem.get("eeg_cmd"),
                    telem.get("final_cmd"),
                    telem.get("eeg_score", 0.0),
                    telem.get("is_moving", False),
                    bci_rc.get("roll", 1500),
                    bci_rc.get("pitch", 1500),
                    bci_rc.get("throttle", 1000),
                    fc_telem.get("rc_roll", 1500),   # From the new MSP_RC we added!
                    fc_telem.get("rc_pitch", 1500),  # From the new MSP_RC we added!
                    fc_telem.get("rc_throttle", 1000),
                    fc_telem.get("roll", 0.0),
                    fc_telem.get("pitch", 0.0),
                    fc_telem.get("yaw", 0.0),
                    fc_telem.get("vbat", 0.0)
                ])

            except BlockingIOError:
                pass

            time.sleep(0.01) # 100Hz max polling

    except KeyboardInterrupt:
        print("\n[Test Interrupted]")

    finally:
        total_time = time.time() - start_time
        csv_file.close()
        main_script_sock.close()

        print("\n==================================================")
        print(f" TEST SUMMARY")
        print("==================================================")
        print(f"Method Used:   {selected_method}")
        print(f"Sequence Goal: {selected_test['sequence']}")
        print(f"Commands Seen: {commands_executed}")
        print(f"Total Time:    {total_time:.2f} seconds")
        print(f"Data Saved To: {filename}")
        print("==================================================")

if __name__ == "__main__":
    main()
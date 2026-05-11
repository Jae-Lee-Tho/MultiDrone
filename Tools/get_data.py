# test_runner.py
import os
import csv
import time
import socket
import json

# =============================================================================
# CONFIGURATION
# =============================================================================
CSV_FILENAME = "experiment_results.csv"
N_TRIALS_PER_COMMAND = 5   # Change this to 10, 20, etc.
TRIAL_TIMEOUT_SEC = 5.0    # How long to wait for a successful command before giving up

EXPERIMENTS =["VOICE_ONLY", "EEG_ONLY", "BOTH"]

COMMANDS =[
    "TAKEOFF", "LAND", "FORWARD", "BACKWARD",
    "LEFT", "RIGHT", "STOP", "UP", "DOWN"
]

# Map commands to the keys server.py expects
COMMAND_TO_KEY = {
    "TAKEOFF": "t", "STOP": "q", "LAND": "l", "UP": "u", "DOWN": "j",
    "RIGHT": "d", "FORWARD": "w", "BACKWARD": "s", "LEFT": "a"
}

# Network setup to talk to main_bci.py and server.py
TELEMETRY_PORT = 4211
telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
telemetry_sock.bind(("0.0.0.0", TELEMETRY_PORT))
telemetry_sock.settimeout(0.02)  # Fast non-blocking reads

SERVER_UDP_IP = "127.0.0.1"
SERVER_UDP_PORT = 4213
server_trigger_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# EEG Threshold matching main_bci.py
CCA_CONFIDENCE_THRESHOLD = 0.65

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def load_completed_trials():
    """Reads the CSV and returns a set of completed trial IDs to support resuming."""
    completed = set()
    if not os.path.exists(CSV_FILENAME):
        # Create file and write headers
        with open(CSV_FILENAME, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Trial_ID", "Experiment_Type", "Target_Command",
                "Voice_Input", "SSVEP_Command", "CCA_Max_Score",
                "CCA_Accepted", "Final_Executed_Command", "Latency_sec"
            ])
        return completed

    with open(CSV_FILENAME, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            completed.add(row["Trial_ID"])
    return completed

def clear_telemetry_buffer():
    """Flushes any old packets out of the socket before starting a new trial."""
    try:
        while True:
            telemetry_sock.recvfrom(4096)
    except socket.timeout:
        pass

# =============================================================================
# MAIN TEST LOOP
# =============================================================================

def run_tests():
    print("=" * 60)
    print("  DRONE FUSION EXPERIMENT RUNNER")
    print("=" * 60)

    completed_trials = load_completed_trials()
    print(f"Loaded {len(completed_trials)} completed trials. Resuming...")

    for exp_type in EXPERIMENTS:

        # Check if we have ANY remaining trials for this experiment block
        needs_run = False
        for cmd in COMMANDS:
            for i in range(1, N_TRIALS_PER_COMMAND + 1):
                if f"{exp_type}_{cmd}_{i}" not in completed_trials:
                    needs_run = True
                    break
            if needs_run: break

        if not needs_run:
            continue # Skip to next experiment if this entire block is done

        print("\n" + "#" * 60)
        print(f"  STARTING EXPERIMENT: {exp_type}")
        print("#" * 60)
        print(f"⚠️  PLEASE ENSURE `self.mode = ExperimentMode.{exp_type}` in main_bci.py!")
        input("Press ENTER when DroneController is running in the correct mode...")

        for target_cmd in COMMANDS:
            for trial_num in range(1, N_TRIALS_PER_COMMAND + 1):
                trial_id = f"{exp_type}_{target_cmd}_{trial_num}"

                if trial_id in completed_trials:
                    continue # Skip already done trials

                print(f"\n--- [ {trial_id} ] ---")

                # --- PREPARE TRIAL ---
                if exp_type in["VOICE_ONLY", "BOTH"]:
                    print(f"🗣️  Get ready to SAY: '{target_cmd}'")
                if exp_type in ["EEG_ONLY", "BOTH"]:
                    print(f"🧠  System will auto-inject EEG for: '{target_cmd}'")

                time.sleep(1.0)
                print("3...")
                time.sleep(1.0)
                print("2...")
                time.sleep(1.0)
                print("1...")
                time.sleep(0.5)

                clear_telemetry_buffer()
                print(">>> GO! <<<")

                start_time = time.time()

                # --- TRIGGER EEG AUTOMATICALLY ---
                if exp_type in ["EEG_ONLY", "BOTH"]:
                    key = COMMAND_TO_KEY[target_cmd]
                    server_trigger_sock.sendto(key.encode('utf-8'), (SERVER_UDP_IP, SERVER_UDP_PORT))

                # --- TRACK METRICS DURING TIMEOUT WINDOW ---
                voice_detected = "NA"
                eeg_detected = "NA"
                final_executed = "NA"
                latency = "NA"
                max_cca_score = 0.0

                if exp_type == "EEG_ONLY":
                    voice_detected = "NA"
                elif exp_type == "VOICE_ONLY":
                    eeg_detected = "NA"

                # Polling Loop
                while time.time() - start_time < TRIAL_TIMEOUT_SEC:
                    try:
                        data, _ = telemetry_sock.recvfrom(4096)
                        telem = json.loads(data.decode("utf-8"))

                        # Track Max CCA Score observed during this trial
                        current_score = telem.get("eeg_score", 0.0)
                        if current_score > max_cca_score:
                            max_cca_score = current_score

                        # Track Voice Recognition
                        if telem.get("voice_cmd"):
                            voice_detected = telem["voice_cmd"]

                        # Track EEG Recognition
                        if telem.get("eeg_cmd"):
                            eeg_detected = telem["eeg_cmd"]

                        # Track Final Fusion Execution
                        if telem.get("final_cmd"):
                            final_executed = telem["final_cmd"]
                            latency = round(time.time() - start_time, 3)
                            print(f"✅ Executed: {final_executed} (Latency: {latency}s)")
                            break  # Success! End trial early.

                    except socket.timeout:
                        continue # No data this tick, keep waiting
                    except json.JSONDecodeError:
                        continue

                # --- TRIAL FINISHED (Success or Timeout) ---
                if final_executed == "NA":
                    print("❌ Timeout reached. Command failed or mismatched.")

                cca_accepted = max_cca_score >= CCA_CONFIDENCE_THRESHOLD

                # --- SAVE ROW TO CSV ---
                row =[
                    trial_id, exp_type, target_cmd,
                    voice_detected, eeg_detected,
                    round(max_cca_score, 4), cca_accepted,
                    final_executed, latency
                ]

                with open(CSV_FILENAME, mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)

                completed_trials.add(trial_id)
                time.sleep(1.0) # Brief pause before next trial

    print("\n🎉 ALL EXPERIMENTS COMPLETED SUCCESSFULLY! Data saved to", CSV_FILENAME)

if __name__ == "__main__":
    try:
        run_tests()
    except KeyboardInterrupt:
        print("\n\n[PAUSED] Test runner stopped by user. Run again to resume.")
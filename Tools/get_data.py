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
N_TRIALS_PER_COMMAND = 5
TRIAL_TIMEOUT_SEC = 5.0

EXPERIMENTS =["VOICE_ONLY", "EEG_ONLY", "BOTH"]

COMMANDS =[
    "TAKEOFF", "LAND", "FORWARD", "BACKWARD",
    "LEFT", "RIGHT", "STOP", "UP", "DOWN"
]

COMMAND_TO_KEY = {
    "TAKEOFF": "t", "STOP": "q", "LAND": "l", "UP": "u", "DOWN": "j",
    "RIGHT": "d", "FORWARD": "w", "BACKWARD": "s", "LEFT": "a"
}

TELEMETRY_PORT = 4211
telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
telemetry_sock.bind(("0.0.0.0", TELEMETRY_PORT))
telemetry_sock.settimeout(0.02)

SERVER_UDP_IP = "127.0.0.1"
SERVER_UDP_PORT = 4213
server_trigger_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# 💡 NEW: UDP Client to remotely set up main_bci.py
MAIN_BCI_IP = "127.0.0.1"
MAIN_BCI_CONTROL_PORT = 4214
bci_control_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

CCA_CONFIDENCE_THRESHOLD = 0.65

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def load_completed_trials():
    completed = set()
    if not os.path.exists(CSV_FILENAME):
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

        needs_run = False
        for cmd in COMMANDS:
            for i in range(1, N_TRIALS_PER_COMMAND + 1):
                if f"{exp_type}_{cmd}_{i}" not in completed_trials:
                    needs_run = True
                    break
            if needs_run: break

        if not needs_run:
            continue

        print("\n" + "#" * 60)
        print(f"  STARTING EXPERIMENT: {exp_type}")
        print("#" * 60)
        print(f"⚙️  Auto-configuring main_bci.py to mode: {exp_type}...")
        input("Press ENTER when you are ready to begin this block...")

        for target_cmd in COMMANDS:
            for trial_num in range(1, N_TRIALS_PER_COMMAND + 1):
                trial_id = f"{exp_type}_{target_cmd}_{trial_num}"

                if trial_id in completed_trials:
                    continue

                print(f"\n---[ {trial_id} ] ---")

                if exp_type in ["VOICE_ONLY", "BOTH"]:
                    print(f"🗣️  Get ready to SAY: '{target_cmd}'")
                if exp_type in["EEG_ONLY", "BOTH"]:
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

                # 💡 FIX: Sync the main_bci script precisely with the trial start time!
                trial_msg = json.dumps({
                    "action": "start_trial",
                    "mode": exp_type,
                    "target": target_cmd
                })
                bci_control_sock.sendto(trial_msg.encode("utf-8"), (MAIN_BCI_IP, MAIN_BCI_CONTROL_PORT))

                start_time = time.time()

                if exp_type in ["EEG_ONLY", "BOTH"]:
                    key = COMMAND_TO_KEY[target_cmd]
                    server_trigger_sock.sendto(key.encode('utf-8'), (SERVER_UDP_IP, SERVER_UDP_PORT))

                voice_detected = "NA"
                eeg_detected = "NA"
                final_executed = "NA"
                latency = "NA"
                max_cca_score = 0.0

                # Polling Loop
                while time.time() - start_time < TRIAL_TIMEOUT_SEC:
                    try:
                        data, _ = telemetry_sock.recvfrom(4096)
                        telem = json.loads(data.decode("utf-8"))

                        if exp_type in ["EEG_ONLY", "BOTH"]:
                            current_score = telem.get("eeg_score", 0.0)
                            if current_score > max_cca_score:
                                max_cca_score = current_score

                            if telem.get("eeg_cmd") and eeg_detected == "NA":
                                eeg_detected = telem["eeg_cmd"]

                        if exp_type in ["VOICE_ONLY", "BOTH"]:
                            if telem.get("voice_cmd") and voice_detected == "NA":
                                voice_detected = telem["voice_cmd"]

                        # Track Final Execution
                        if telem.get("final_cmd"):
                            final_executed = telem["final_cmd"]
                            decision_time = telem.get("decision_time", time.time())
                            voice_onset = telem.get("voice_onset_time", 0.0)

                            # 💡 FIX: Mathematically pure system latency mapping
                            if exp_type == "VOICE_ONLY":
                                if voice_onset > 0.0:
                                    latency_val = decision_time - voice_onset
                                else:
                                    latency_val = decision_time - start_time # Fallback
                            elif exp_type == "EEG_ONLY":
                                latency_val = decision_time - start_time
                            elif exp_type == "BOTH":
                                if voice_onset > 0.0:
                                    first_signal = min(start_time, voice_onset)
                                else:
                                    first_signal = start_time
                                latency_val = decision_time - first_signal
                            else:
                                latency_val = decision_time - start_time

                            latency = round(latency_val, 3)
                            break

                    except socket.timeout:
                        continue
                    except json.JSONDecodeError:
                        continue

                cca_accepted = max_cca_score >= CCA_CONFIDENCE_THRESHOLD

                print("\n" + "="*45)
                print(f" 📊 TRIAL RESULTS: {trial_id}")
                print("="*45)
                print(f" Target Command  : {target_cmd}")
                print(f" Voice Detected  : {voice_detected}")
                print(f" EEG Detected    : {eeg_detected}")
                print(f" CCA Max Score   : {max_cca_score:.4f}")
                print(f" CCA Accepted?   : {cca_accepted}")
                print(f" Final Executed  : {final_executed}")
                print(f" Latency (sec)   : {latency}")
                print("="*45)

                if final_executed == "NA":
                    print("❌ Timeout reached. Command failed or mismatched.")
                else:
                    print("✅ Command executed successfully!")

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
                time.sleep(1.0)

    print("\n🎉 ALL EXPERIMENTS COMPLETED SUCCESSFULLY! Data saved to", CSV_FILENAME)

if __name__ == "__main__":
    try:
        run_tests()
    except KeyboardInterrupt:
        print("\n\n[PAUSED] Test runner stopped by user. Run again to resume.")
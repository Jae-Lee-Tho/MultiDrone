import socket
import json
import time
import csv
import os
import threading
from datetime import datetime

TELEMETRY_IP = "0.0.0.0"
TELEMETRY_PORT = 4211
ESP32_TELEMETRY_PORT = 4212

recording = True

def load_sequences():
    with open('test_sequences.json', 'r') as f:
        return json.load(f)["tests"]

def end_test_monitor():
    global recording
    input("\n[PRESS ENTER TO END THE TEST AND SAVE DATA]\n")
    recording = False

def main():
    global recording
    print("========================================")
    print("   DRONE METHOD COMPARISON TEST RUNNER")
    print("========================================")

    # Select method
    methods = ["VOICE_ONLY", "EMG_ONLY", "VOICE_AND_EMG", "PHYSICAL_CONTROLLER"]
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

    # Setup UDP sockets
    pi_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pi_sock.bind((TELEMETRY_IP, TELEMETRY_PORT))
    pi_sock.setblocking(False)

    esp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    esp_sock.bind((TELEMETRY_IP, ESP32_TELEMETRY_PORT))
    esp_sock.setblocking(False)

    # Setup CSV logging
    os.makedirs('results', exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"results/{selected_method}_{selected_test['name'].replace(' ', '_')}_{timestamp_str}.csv"

    csv_file = open(filename, 'w', newline='')
    writer = csv.writer(csv_file)
    writer.writerow([
        "system_time", "source", "test_method", "test_name",
        "drone_state", "voice_cmd", "emg_cmd", "final_cmd",
        "is_moving", "rc_roll", "rc_pitch", "rc_throttle", "rc_yaw", "rc_arm",
        "fc_roll_angle", "fc_pitch_angle", "fc_yaw_angle", "fc_voltage", "fc_current"
    ])

    print(f"\n[Ready] Logging data to: {filename}")
    print("[Ready] Ensure Raspberry_Pi.py and ESP32_Firmware are running!")

    print("\n==================================================")
    print(f" GOAL SEQUENCE: {selected_test['sequence']}")
    print("==================================================")
    print("The test is NOW RECORDING telemetry in the background.")
    print("Perform Take Off, the full sequence, and Land.")
    print("Press ENTER at any time to finish the test and save the data.")
    print("==================================================\n")

    threading.Thread(target=end_test_monitor, daemon=True).start()

    last_fc_telemetry = {"roll": 0, "pitch": 0, "yaw": 0, "vbat": 0.0, "current": 0.0}

    try:
        while recording:
            # Check for ESP32/FC Telemetry
            try:
                data, _ = esp_sock.recvfrom(2048)
                fc_telem = json.loads(data.decode('utf-8'))
                if fc_telem.get("type") == "attitude":
                    last_fc_telemetry["roll"] = fc_telem["roll"]
                    last_fc_telemetry["pitch"] = fc_telem["pitch"]
                    last_fc_telemetry["yaw"] = fc_telem["yaw"]
                    writer.writerow([
                        time.time(), "fc_attitude", selected_method, selected_test["name"],
                        "", "", "", "", "", "", "", "", "", "",
                        fc_telem["roll"], fc_telem["pitch"], fc_telem["yaw"], last_fc_telemetry["vbat"], last_fc_telemetry["current"]
                    ])
                elif fc_telem.get("type") == "analog":
                    last_fc_telemetry["vbat"] = fc_telem["vbat"]
                    last_fc_telemetry["current"] = fc_telem["current"]
                    writer.writerow([
                        time.time(), "fc_analog", selected_method, selected_test["name"],
                        "", "", "", "", "", "", "", "", "", "",
                        last_fc_telemetry["roll"], last_fc_telemetry["pitch"], last_fc_telemetry["yaw"], fc_telem["vbat"], fc_telem["current"]
                    ])
            except BlockingIOError:
                pass

            # Check for Raspberry Pi Telemetry
            try:
                data, _ = pi_sock.recvfrom(2048)
                telem = json.loads(data.decode('utf-8'))

                if telem.get("final_cmd"):
                    print(f" -> Executed: {telem['final_cmd']}")
                elif telem.get("voice_cmd") or telem.get("emg_cmd"):
                    print(f" -> Detected (Dropped/Blocked): Voice='{telem.get('voice_cmd')}', EMG='{telem.get('emg_cmd')}'")

                rc = telem["rc_channels"]
                writer.writerow([
                    time.time(), "pi", selected_method, selected_test["name"],
                    telem["state"], telem["voice_cmd"], telem["emg_cmd"], telem["final_cmd"],
                    telem["is_moving"], rc["roll"], rc["pitch"], rc["throttle"], rc["yaw"], rc["arm"],
                    last_fc_telemetry["roll"], last_fc_telemetry["pitch"], last_fc_telemetry["yaw"],
                    last_fc_telemetry["vbat"], last_fc_telemetry["current"]
                ])
            except BlockingIOError:
                pass

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[Test Interrupted]")

    finally:
        csv_file.close()
        pi_sock.close()
        esp_sock.close()
        print(f"\n[Finished] Saved test data to {filename}")

if __name__ == "__main__":
    main()

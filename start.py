import platform
import subprocess
import os
import time

def start_windows():
    print("Detected OS: Windows")
    # Open ESP32 in a new Command Prompt
    subprocess.Popen('start "Drone: ESP32" cmd /k "node ESP32/ESP32_Firmware.js"', shell=True)
    time.sleep(2)
    # Open Raspberry Pi in a new Command Prompt
    subprocess.Popen('start "Ground Station: Raspberry Pi" cmd /k "cd Raspberry_Pi && python raspberry_pi.py"', shell=True)

def start_mac():
    print("Detected OS: macOS")
    current_dir = os.path.abspath(os.path.dirname(__file__))

    # AppleScript commands to open new Terminal windows
    esp_cmd = f'''osascript -e 'tell application "Terminal" to do script "cd \\"{current_dir}\\" && node ESP32/ESP32_Firmware.js"' '''
    pi_cmd = f'''osascript -e 'tell application "Terminal" to do script "cd \\"{current_dir}/Raspberry_Pi\\" && python3 Raspberry_Pi.py"' '''

    subprocess.Popen(esp_cmd, shell=True)
    time.sleep(2)
    subprocess.Popen(pi_cmd, shell=True)

def start_linux():
    print("Detected OS: Linux (Headless/SSH mode)")
    try:
        # Run directly in the current terminal, piping output to the same screen
        # We use a list format for Popen which is safer and doesn't require shell=True
        esp_process = subprocess.Popen(["node", "ESP32/ESP32_Firmware.js"])
        time.sleep(2)
        pi_process = subprocess.Popen(["python3", "Raspberry_Pi.py"], cwd="Raspberry_Pi")

        print("\n==================================================")
        print("Both systems are running in this terminal.")
        print("Press Ctrl+C to stop both processes.")
        print("==================================================\n")

        # Keep the main script alive so we see the output, and wait for them to finish
        esp_process.wait()
        pi_process.wait()

    except KeyboardInterrupt:
        # Catch Ctrl+C to cleanly kill both background processes before exiting
        print("\nShutting down systems...")
        esp_process.terminate()
        pi_process.terminate()
    except Exception as e:
        print(f"Failed to start processes: {e}")

if __name__ == "__main__":
    print("==================================================")
    print("  Booting Drone Control System Test Environment")
    print("==================================================\n")

    os_name = platform.system()

    if os_name == "Windows":
        start_windows()
    elif os_name == "Darwin":
        start_mac()
    elif os_name == "Linux":
        start_linux()
    else:
        print(f"Unsupported OS: {os_name}. Please open the files manually.")

    print("\nStarting systems... You can safely close this launcher window.")
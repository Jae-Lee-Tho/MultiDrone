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
    subprocess.Popen('start "Ground Station: Raspberry Pi" cmd /k "cd Raspberry_Pi && python Raspberry_Pi.py"', shell=True)

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
    print("Detected OS: Linux")
    # Using gnome-terminal (standard on Ubuntu and many other distros)
    esp_cmd = 'gnome-terminal --title="Drone: ESP32" -- bash -c "node ESP32/ESP32_Firmware.js; exec bash"'
    pi_cmd = 'gnome-terminal --title="Ground Station" -- bash -c "cd Raspberry_Pi && python3 Raspberry_Pi.py; exec bash"'

    try:
        subprocess.Popen(esp_cmd, shell=True)
        time.sleep(2)
        subprocess.Popen(pi_cmd, shell=True)
    except Exception as e:
        print(f"Failed to open Linux terminals: {e}")
        print("Note: If you aren't using gnome-terminal, you may need to edit this script for xterm or konsole.")

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
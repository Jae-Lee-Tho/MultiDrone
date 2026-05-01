# 🧠🚁 Multimodal BCI (EEG + Voice) Drone Control System

Welcome to the **Multimodal Brain-Computer Interface Drone Controller**. This repository contains a complete, production-ready pipeline for controlling a Betaflight-based FPV drone using a fusion of **Brainwaves (EEG)** and **Voice Commands**.

This system was built to study the latency, cognitive load, and reliability of different control modalities (Voice, EEG, Fusion, and Physical Controller) and includes a comprehensive suite of tools for academic data collection and experimental research.

## 🎯 Project Overview

This project combines **Brain-Computer Interfaces (BCI)** with voice recognition to create a novel multi-modal drone control system. Unlike traditional joystick controllers, pilots can control drones using:
- **Voice commands** (e.g., "Forward", "Left", "Land")
- **SSVEP-based EEG control** (Steady-State Visually Evoked Potential brainwave detection)
- **Fusion mode** (requiring simultaneous brain and voice signals for redundancy)
- **Traditional physical RC controllers** (for baseline comparison)

The system captures real-time telemetry data and generates detailed CSV logs for research analysis, making it ideal for academic poster presentations and human-factors studies.

---

## 📑 Table of Contents
1. [Project Overview](#-project-overview)
2. [System Architecture](#-system-architecture)
3. [Hardware & Software Requirements](#-hardware--software-requirements)
4. [Installation & Setup](#-installation--setup)
5. [Pre-Flight Setup (Do This First!)](#-pre-flight-setup-do-this-first)
6. [Quick Start Guide](#-quick-start-guide)
7. [How to Run the System](#-how-to-run-the-system)
8. [Data Collection (Test Runner)](#-data-collection-test-runner)
9. [Simulating EEG for Field Tests](#-simulating-eeg-for-field-tests)
10. [Directory Structure](#-directory-structure)
11. [Configuration Guide](#-configuration-guide)
12. [Troubleshooting & FAQs](#-troubleshooting--faqs)
13. [Contributing](#-contributing)
14. [License](#-license)

---

## 🏗️ System Architecture

Unlike standard drone controllers, this system replaces physical joysticks with cognitive and auditory inputs. The data flow is orchestrated across multiple devices and protocols:

```text
[OpenBCI Headset] ----(LSL)----> [Laptop]                 [Physical Radio]
                                    |                            |
[Microphone] ------(Audio)-----> [main_bci.py]                   | (2.4 GHz)
                                    |                            |
                             (Wi-Fi / UDP)                       |
                                    |                            |
[Test Runner] <---(UDP)--------- [ESP32] ---(UART/MSP)---> [Flight Controller]
(Logs CSVs)                          |
                                     v
                            [Betaflight Drone]
```

### Signal Processing Pipeline

1. **EEG Acquisition:** Brainwaves are read via OpenBCI and broadcast over a local network via **LSL (Lab Streaming Layer)**.
2. **Voice Acquisition:** Voice is captured via the laptop microphone using real-time audio streaming.
3. **Signal Processing:**
   - **CCA (Canonical Correlation Analysis)** detects SSVEP frequencies in the brainwaves at 8Hz, 14Hz, and 17Hz
   - **Vosk** performs offline speech recognition (no internet required)
4. **Command Fusion:** When in Fusion mode, the system waits for simultaneous EEG and voice confirmation.
5. **Transmission:** Commands are mapped to standard RC values (1000-2000 µs PWM) and sent over Wi-Fi (UDP) to the ESP32.
6. **Execution:** The ESP32 formats these values into **MSP (MultiWii Serial Protocol)** packets and injects them directly into the drone's Betaflight flight controller.
7. **Telemetry Feedback:** Drone status (attitude, battery voltage) is streamed back to the laptop in real-time for logging.

### 📡 Port Map
| Port | Direction | Purpose |
|------|-----------|---------|
| `4210` | Laptop → ESP32 | Sending drone commands |
| `4212` | ESP32 → Laptop | Receiving drone telemetry & battery |
| `4211` | Main Script → Test Runner | Logging data to CSV |
| LSL stream | OpenBCI → Laptop | EEG data over local network |

---

## 🛠️ Hardware & Software Requirements

### Hardware
| Component | Specification | Notes |
|-----------|---------------|-------|
| **Drone** | FPV drone running Betaflight v4.0+ | Any brushless quadcopter |
| **Flight Controller** | Betaflight-compatible (F3, F4, F7) | Must support MSP over UART |
| **Wireless Bridge** | ESP32 Dev Board | Soldered to drone's UART RX/TX pads |
| **EEG Headset** | OpenBCI Cyton or compatible | Needs Occipital lobe electrodes (O1, O2, Oz) |
| **Failsafe** | Physical RC Transmitter | Bound to drone for emergency takeovers |
| **Laptop** | Windows/Mac/Linux with USB | Runs main BCI script and test runner |

### Software Dependencies

The project uses both Python and JavaScript components:

**Python (Main stack):**
```bash
pip install -r requirements.txt
```

**Node.js (ESP32 firmware):**
```bash
npm install
```

**Additional Requirements:**
1. **Speech Model:** Download the [Vosk Small English Model (vosk-model-small-en-us-0.15)](https://alphacephei.com/vosk/models) and extract the folder into the project root directory.
2. **Arduino IDE:** Required to flash the ESP32 firmware. Install "ESP32 by Espressif Systems" board package.
3. **Betaflight Configurator:** Download from [betaflight.com](https://betaflight.com/) for flight controller configuration.
4. **OpenBCI GUI:** Optional, but recommended for EEG visualization. Download from [openbci.com](https://openbci.com/)

---

## 📦 Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/khoy2k/droneProject.git
cd droneProject
```

### 2. Install Python Dependencies
```bash
# Using pip
pip install -r requirements.txt

# OR using uv (faster alternative)
uv sync
```

### 3. Install Node.js Dependencies (for ESP32)
```bash
npm install
```

### 4. Download Vosk Speech Model
```bash
# Download from: https://alphacephei.com/vosk/models
# Extract vosk-model-small-en-us-0.15/ to the project root
unzip vosk-model-small-en-us-0.15.zip
```

### 5. Verify Installation
```bash
# Test voice recognition
python voice_test.py

# Test EEG simulation
python OPEN_BCI/eeg_simulator.py --help
```

---

## 🚀 Pre-Flight Setup (Do This First!)

**⚠️ CRITICAL: Remove the drone propellers before doing this.**

Before running the main BCI script, you must prepare the hardware and calibrate the movement speeds.

### 1. Flash and Wire the ESP32

1. **Open Arduino IDE** and load `ESP32/ESP32_Firmware.ino`
2. **Configure WiFi:**
   - Update the `WIFI_SSID` and `WIFI_PASSWORD` variables to match your local network
   - Alternatively, set `WIFI_MODE` to `WIFI_SOFTAP` for the ESP32 to host its own network (recommended for field testing)
3. **Select Board:** Set Tools → Board → "ESP32 Dev Module"
4. **Set Baud Rate:** Tools → Upload Speed → "115200"
5. **Flash the firmware:** Click Upload
6. **Wire to Drone:**
   - Connect **ESP32 GPIO 17 (TX)** to a free **RX pad** on your flight controller
   - Connect **5V** from ESP32 to 5V pad on flight controller
   - Connect **GND** from ESP32 to GND pad on flight controller
   - Use a UART pad that isn't already in use (check your FC documentation)

### 2. Configure Betaflight

1. **Open Betaflight Configurator**
2. **Connect to your drone** (via USB)
3. **Ports Configuration:**
   - Go to the **Ports** tab
   - Find the UART you soldered the ESP32 to
   - Enable **MSP** protocol
   - Set baud rate to **115200**
   - Save and reboot the drone
4. **Verify MSP is active** in the CLI: `serialports`

### 3. Calibrate RC Values

Each drone has unique weight and power characteristics, so we cannot hardcode hover or forward speeds.

1. **Power on** your physical RC transmitter and drone
2. **Run the calibration script:**
   ```bash
   python Tools/calibrate_rc.py
   ```
3. **Follow the prompts:**
   - The script will ask you to move the throttle to a "good hover height"
   - Then push forward stick to a "good forward speed"
   - Press Enter after each movement
4. **Copy the output values** and paste them into Section 9 (`RC_VALUES` dict) of `main_bci.py`

---

## 🎮 Quick Start Guide

Once you've completed the pre-flight setup, here's the fastest way to get flying:

```bash
# Terminal 1: Start the main BCI script
python main_bci.py

# Terminal 2 (after a few seconds): Start the OpenBCI GUI
# (If using real EEG data)

# Terminal 3 (optional): Run test sequences
python test/test_runner.py
```

**To Fly:**
1. Speak: *"Take off"*
2. Look at the SSVEP flickering screen (or speak commands)
3. Use voice commands: *"Forward", "Left", "Right", "Backward", "Stop"*
4. Speak: *"Land"* to descend

---

## 🎮 How to Run the System

### Step 1: Select Control Mode
Open `main_bci.py` and set your desired `EXPERIMENT_MODE` (Section 1):
- **`VOICE_ONLY`:** Responds only to spoken commands
- **`EEG_ONLY`:** Responds only to detected SSVEP frequencies
- **`BOTH` (Fusion):** Requires **both** sensors to detect the same command simultaneously (most reliable)
- **`PHYSICAL_RC`:** Ignores BCI, allows standard controller flying (for baseline data collection)

### Step 2: Start the System
```bash
# Terminal 1: Main BCI script
python main_bci.py
```

If using real EEG data:
```bash
# Terminal 2: Start OpenBCI GUI
# (This broadcasts the EEG stream via LSL)
# Download from: https://openbci.com/
```

### Step 3: Send Commands

**Voice Commands:**
```
"Take off"  - Lift drone to hover height
"Land"      - Descend to ground
"Forward"   - Move forward
"Backward"  - Move backward
"Left"      - Strafe left
"Right"     - Strafe right
"Stop"      - Emergency stop (armed kill-switch)
```

**EEG Commands (using SSVEP):**
- Look at 8Hz flicker: **Forward**
- Look at 14Hz flicker: **Backward**
- Look at 17Hz flicker: **Left/Right toggle**

**Fusion Mode Workflow:**
1. Stare at the SSVEP target (8Hz, 14Hz, or 17Hz)
2. Wait 1-2 seconds for EEG buffer to fill
3. Speak the matching command (e.g., *"Forward"*)
4. Command executes only if both sensors agree

---

---

## 📊 Data Collection (Test Runner)

For academic research and poster presentations, the project includes a sophisticated data collection framework. The `test_runner.py` script runs in the background and prompts users with predefined sequences while logging comprehensive telemetry data.

### How to Run a Test

1. **Start the main system** in one terminal:
   ```bash
   python main_bci.py
   ```

2. **Open a second terminal** and run the test runner:
   ```bash
   python test/test_runner.py
   ```

3. **Select your configuration:**
   - Choose the control modality (Voice Only, EEG Only, Fusion, Physical RC)
   - Select difficulty level (Easy, Medium, Expert)
   - Enter pilot name and any notes

4. **Follow the on-screen prompts:**
   - The script will tell you each command to execute
   - Execute the command using your selected control method
   - The drone's response is verified automatically via telemetry

5. **Results are automatically saved** to `test/results/` with timestamp

### CSV Output Format

The generated CSV includes:
| Column | Description |
|--------|-------------|
| `Timestamp` | Unix timestamp for each sample |
| `Elapsed_Time` | Seconds since test start |
| `Command_Requested` | What the test asked for |
| `Command_Recognized` | What the BCI system recognized |
| `Command_Executed` | Whether the drone acted on it |
| `EEG_Confidence` | CCA confidence score (0-1) |
| `Voice_Confidence` | Speech recognition confidence (0-1) |
| `Drone_Roll` | Drone roll angle (degrees) |
| `Drone_Pitch` | Drone pitch angle (degrees) |
| `Drone_Yaw` | Drone yaw angle (degrees) |
| `Battery_Voltage` | Current battery voltage |
| `Reaction_Time_ms` | Human reaction time to prompt |
| `Command_Latency_ms` | Time from voice/EEG to drone response |

### Data Analysis

Once you have collected CSV files, analyze them:
```bash
python test/data_analysis_example.py
```

This generates plots showing:
- RC channel evolution over time
- Response latency comparisons
- Success rate by modality
- Cognitive load metrics

---

## 🧪 Simulating EEG for Field Tests

Flying a drone safely requires being outside, but obtaining clean EEG data requires a controlled lab environment. The **Record & Playback pipeline** solves this:

### Step 1: In the Lab (Record)

Sit in a controlled lab environment with the EEG cap properly fitted. Record your brainwaves while looking at the SSVEP visual stimuli:

```bash
python OPEN_BCI/eeg_simulator.py record -f my_eeg_data.csv -d 300
```

Options:
- `-f` / `--file`: Output CSV filename
- `-d` / `--duration`: Recording duration in seconds (300s = 5 minutes)
- `-c` / `--channels`: Number of EEG channels (default: 8)

### Step 2: In the Field (Playback)

Take your laptop and the recorded EEG CSV file to the field. Broadcast the recorded brainwaves to trick `main_bci.py` into thinking the headset is connected:

```bash
python OPEN_BCI/eeg_simulator.py play -f my_eeg_data.csv
```

Now start `main_bci.py` in another terminal and fly outside!

```bash
python main_bci.py  # in another terminal
```

### Test without EEG

If you don't have an EEG headset, you can still test the voice control and physical controller modes:

```bash
# Generate mock EEG data for testing
python OPEN_BCI/mock_server.py
```

---

## 📂 Directory Structure

```
droneProject/
├── 📄 main_bci.py                 # Central hub: DSP, voice recognition, command logic
├── 📄 start.py                    # Multi-platform startup script (Windows/Mac/Linux)
├── 📄 voice_test.py               # Quick test for voice recognition
├── 📄 requirements.txt             # Python dependencies
├── 📄 pyproject.toml              # Project metadata (UV/Poetry)
├── 📄 package.json                # Node.js dependencies
│
├── 📁 ESP32/                      # Wireless bridge firmware
│   ├── 📄 ESP32_Firmware.ino      # C++ firmware (Arduino)
│   └── 📄 ESP32_Firmware.js       # JavaScript interface
│
├── 📁 FlightController/           # Betaflight-specific code
│   └── 📄 Betaflight.js           # Flight controller integration
│
├── 📁 Raspberry_Pi/               # Ground station (optional)
│   ├── 📄 Raspberry_Pi.py         # Ground telemetry aggregator
│   └── 📁 vosk-model-small-en-us-0.15/  # Offline speech model
│
├── 📁 OPEN_BCI/                   # EEG and simulation tools
│   ├── 📄 calibrate.py            # EEG electrode calibration
│   ├── 📄 eeg_simulator.py        # Record/playback EEG streams
│   ├── 📄 mock_server.py          # Generate mock EEG for testing
│   └── 📄 test.py                 # Unit tests for EEG processing
│
├── 📁 Tools/                      # Utility scripts
│   ├── 📄 calibrate_rc.py         # RC channel calibration wizard
│   └── 📄 ssvep.html              # Visual stimuli generator (8/14/17 Hz)
│
├── 📁 test/                       # Data collection framework
│   ├── 📄 test_runner.py          # Interactive test prompter
│   ├── 📄 test_sequences.json     # Test difficulty definitions
│   ├── 📄 data_analysis_example.py # CSV analysis & plotting
│   ├── 📄 README.md               # Test framework documentation
│   └── 📁 results/                # CSV logs and plots
│
└── 📁 .venv/                      # Virtual environment (auto-created)
```

### Key Files Explained

| File | Purpose |
|------|---------|
| `main_bci.py` | Core BCI engine - DSP filtering, voice recognition, EEG processing, drone control logic |
| `ESP32/ESP32_Firmware.ino` | Embedded C++ code for wireless bridge - Wi-Fi to UART MSP translation |
| `test_runner.py` | Automated test framework - generates research CSV files with telemetry |
| `test_sequences.json` | Test difficulty profiles (Easy/Medium/Hard with command sequences) |
| `calibrate_rc.py` | Interactive setup wizard to map RC stick movements |
| `eeg_simulator.py` | Record lab EEG data and playback for field testing |
| `ssvep.html` | HTML5 visual stimuli (8Hz, 14Hz, 17Hz flickering frequencies) |
| `voice_test.py` | Standalone voice recognition tester |

---

## ⚙️ Configuration Guide

### Main Configuration (`main_bci.py`)

**Section 1: Experiment Mode**
```python
EXPERIMENT_MODE = "BOTH"  # "VOICE_ONLY" | "EEG_ONLY" | "BOTH" | "PHYSICAL_RC"
```

**Section 2: EEG Settings**
```python
EEG_LSL_STREAM_NAME = "OpenBCI"    # Name of LSL stream from OpenBCI GUI
EEG_WINDOW_LENGTH = 2.0             # Seconds of EEG data to buffer for CCA
EEG_TARGET_FREQUENCIES = [8, 14, 17]  # SSVEP target frequencies (Hz)
EEG_CONFIDENCE_THRESHOLD = 0.6      # Min CCA correlation to accept command
```

**Section 3: Voice Settings**
```python
VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"
VOICE_CONFIDENCE_THRESHOLD = 0.7
COMMAND_COOLDOWN = 1.0              # Min seconds between consecutive commands
```

**Section 4: Network Settings**
```python
ESP32_IP = "192.168.1.100"          # ESP32 IP address
ESP32_CMD_PORT = 4210               # Commands to drone
ESP32_TELEMETRY_PORT = 4212         # Telemetry from drone
TEST_RUNNER_PORT = 4211             # Logging port
```

**Section 9: RC Values (from calibration)**
```python
RC_VALUES = {
    "THROTTLE_HOVER": 1500,
    "THROTTLE_MAX": 1950,
    "PITCH_MAX": 1600,
    "ROLL_MAX": 1600,
    "YAW_RATE": 500,
}
```

### ESP32 Configuration (`ESP32/ESP32_Firmware.ino`)

**WiFi Settings (Line ~20):**
```cpp
const char* WIFI_SSID = "your-network-name";
const char* WIFI_PASSWORD = "your-password";
const int WIFI_MODE = WIFI_STA;  // WIFI_STA or WIFI_SOFTAP
```

**UART Settings (Line ~40):**
```cpp
const int MSP_UART = 1;          // UART 1 (RX=10, TX=17)
const int BAUD_RATE = 115200;    // Must match Betaflight config
```

**Failsafe Settings (Line ~60):**
```cpp
const unsigned long WATCHDOG_TIMEOUT = 500;  // ms, if no command received
const int FAILSAFE_THROTTLE = 1000;          // Emergency cut value
```

### Betaflight Configuration

After flashing ESP32, configure your flight controller:

1. **Ports Tab:**
   - Set UART to MSP protocol at 115200 baud
   - Example: UART3 → MSP

2. **CLI Commands:**
   ```
   # Verify MSP is configured
   serialports

   # Set deadband for cleaner control
   set deadband = 5
   set yaw_deadband = 5

   # Save
   save
   ```

---

## ⚠️ Troubleshooting & FAQs

### Common Issues

#### 1. "Address already in use" Error
**Problem:** Script fails to bind to UDP port.
**Solution:**
```bash
# Check what's using port 4210
netstat -ano | findstr :4210  # Windows
lsof -i :4210                 # Mac/Linux

# Kill the process and retry
```

#### 2. "No OpenBCI LSL Stream Found"
**Problem:** EEG data not being received.
**Solutions:**
- Ensure OpenBCI GUI is running and broadcasting LSL
- Check that EEG headset is powered and connected
- Run mock server for testing:
  ```bash
  python OPEN_BCI/mock_server.py
  ```

#### 3. Calibration Script Isn't Reading Sticks
**Problem:** `calibrate_rc.py` says "waiting for input" but nothing happens.
**Cause:** Betaflight RC Lockout - the FC ignores physical controllers while receiving MSP commands.
**Solution:** Close `main_bci.py` before running `calibrate_rc.py`

#### 4. Calibration Script Says "Move Throttle" but Yaw Changes
**Problem:** RC channels are mapped incorrectly.
**Cause:** AETR vs TAER mismatch between radio and flight controller.
**Solution:**
1. Open `ESP32/ESP32_Firmware.ino`
2. Find Section 5: MSP_RC array parser (around line 150)
3. Swap the indexes until they match your radio layout:
   ```cpp
   // Example: if Yaw moves when you want Throttle
   mspRC[0] = cmdArray[0];  // Throttle
   mspRC[1] = cmdArray[1];  // Pitch
   mspRC[2] = cmdArray[3];  // Roll (swap with...)
   mspRC[3] = cmdArray[2];  // Yaw
   ```

#### 5. Drone Doesn't React to STOP Command
**Problem:** Stop command works but drone keeps moving.
**Cause:** Depending on configuration, STOP can be an emergency kill-switch.
**Solutions:**
- Check the `apply_command()` function in `main_bci.py`
- If drone is GROUNDED, send TAKEOFF first
- Verify the drone isn't in failsafe mode

#### 6. Voice Recognition Keeps Getting Wrong Commands
**Problem:** Speech recognition accuracy is low.
**Solutions:**
- Lower `VOICE_CONFIDENCE_THRESHOLD` in `main_bci.py`
- Increase ambient noise rejection (add noise profile)
- Speak clearly and at normal volume
- Try the larger Vosk model: `vosk-model-en-us-0.42-gigaspeech`

#### 7. EEG CCA Confidence is Always Low (<0.3)
**Problem:** SSVEP detection not working well.
**Causes:**
- Eye strain (need to stare at flicker for 3-5 seconds)
- Electrodes not making good contact
- Window length too short
- Noise on EEG channels
**Solutions:**
- Increase `EEG_WINDOW_LENGTH` to 3.0-4.0 seconds
- Reduce `EEG_CONFIDENCE_THRESHOLD` (temporarily)
- Re-fit EEG cap and check electrode gel
- Check for 50/60Hz mains noise in raw signal

#### 8. ESP32 Keeps Disconnecting from WiFi
**Problem:** WiFi connection drops frequently.
**Solutions:**
- Switch to WIFI_SOFTAP mode (ESP32 hosts network)
- Move ESP32 closer to router
- Check for WiFi interference (2.4GHz congestion)
- Reduce transmit power (line ~70 in ESP32_Firmware.ino):
  ```cpp
  WiFi.setTxPower(WIFI_POWER_8dBm);
  ```

---

## 🔧 Advanced Tips

### Recording for Debugging
```python
# In main_bci.py, enable logging
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Testing Individual Components
```bash
# Test voice only
python voice_test.py

# Test EEG simulation
python OPEN_BCI/eeg_simulator.py play -f sample_data.csv

# Test ESP32 connection
python -c "import socket; s=socket.socket(); s.connect(('192.168.1.100', 4210)); print('ESP32 Connected!')"
```

### Manually Sending Commands to Drone
```bash
# Send via UDP to ESP32
python -c "
import socket
s = socket.socket()
s.connect(('192.168.1.100', 4210))
s.send(b'TAKEOFF')  # or FORWARD, LEFT, etc.
s.close()
"
```

---

## 📚 References & Resources

- **OpenBCI Documentation:** [docs.openbci.com](https://docs.openbci.com/)
- **Betaflight GitHub:** [github.com/betaflight/betaflight](https://github.com/betaflight/betaflight)
- **ESP32 Arduino Core:** [github.com/espressif/arduino-esp32](https://github.com/espressif/arduino-esp32)
- **Vosk Offline Recognition:** [github.com/alphacep/vosk-api](https://github.com/alphacep/vosk-api)
- **Lab Streaming Layer (LSL):** [github.com/sccn/labstreaminglayer](https://github.com/sccn/labstreaminglayer)
- **CCA Algorithm:** [Paper on SSVEP Recognition via CCA](https://doi.org/10.1016/j.brainres.2006.09.037)

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Make your changes** and test thoroughly
4. **Commit with clear messages** (`git commit -m "Add amazing feature"`)
5. **Push to the branch** (`git push origin feature/amazing-feature`)
6. **Open a Pull Request** with a description of your changes

### Areas for Contribution
- [ ] Additional speech commands (e.g., "Hover", "Rotate")
- [ ] Alternative EEG frequency markers
- [ ] Mobile app for remote monitoring
- [ ] Improved telemetry visualization
- [ ] Raspberry Pi ground station enhancements
- [ ] Documentation translations

---

## 📄 License

This project is licensed under the **MIT License**. See the LICENSE file for details.

---

## 🙏 Acknowledgments

- **OpenBCI Community** for excellent EEG hardware and documentation
- **Betaflight Project** for the flight controller firmware
- **Vosk Project** for offline speech recognition
- All contributors and testers who helped debug and improve this system

---

## 📞 Support & Contact

For issues, questions, or suggestions:
- **Open an Issue** on GitHub
- **Check Troubleshooting** section above
- **Review test logs** in `/test/results/` for debugging

---

*Built for Poster Presentations & BCI Research. Fly Safe!* 🚁🧠
# 🧠🚁 Multimodal BCI (Mock EEG + Voice) Drone Control System

Welcome to the **Multimodal Brain-Computer Interface Drone Controller**. This repository contains a complete pipeline for controlling a Betaflight-based FPV drone using a fusion of **Brainwaves (SSVEP EEG)** and **Voice Commands**.

**Update:** To ensure high reliability during field testing and demonstrations, this system now utilizes a local server broadcasting the highly-validated **Nakanishi SSVEP Dataset** over Lab Streaming Layer (LSL), acting as a mock EEG headset.

## 🎯 Project Overview

Pilots can control the drone using:
- **Voice commands** (e.g., "Forward", "Left", "Land") via Vosk offline speech recognition.
- **SSVEP-based EEG control** via CCA (Canonical Correlation Analysis) matching 8-channel EEG data to predefined frequencies.
- **Fusion mode** (requiring simultaneous brain and voice signals for redundancy and safety).
- **Traditional physical RC controllers** (for baseline comparison).

---

## 📑 Table of Contents
1. [System Architecture](#-system-architecture)
2. [Frequency & Command Mapping](#-frequency--command-mapping)
3. [Hardware & Software Requirements](#-hardware--software-requirements)
4. [Installation & Setup](#-installation--setup)
5. [Pre-Flight Setup (Hardware)](#-pre-flight-setup-hardware)
6. [How to Run the System](#-how-to-run-the-system)
7. [Directory Structure](#-directory-structure)
8.[Configuration & Tuning Guide](#-configuration--tuning-guide)
9. [Troubleshooting & FAQs](#-troubleshooting--faqs)

---

## 🏗️ System Architecture

The system replaces physical joysticks with cognitive and auditory inputs. Data flows across multiple devices and protocols:

    [server.py (Nakanishi Dataset)] --(LSL)--> [Laptop]               [Physical Radio]
                                                  |                          |
    [Microphone] -------------(Audio)--------> [main_bci.py]                 | (2.4 GHz)
                                                  |                          |
                                            (Wi-Fi / UDP)                    |
                                                  |                          |[Test Runner] <---(UDP)------------------- [ESP32] ---(UART/MSP)--->[Flight Controller]
    (Logs CSVs)                                   |
                                                  v
                                         [Betaflight Drone]

### 📡 Port & Protocol Map
| Component | Protocol | Port/Name | Purpose |
|-----------|----------|-----------|---------|
| Laptop → ESP32 | UDP | 4210 | Sending Roll, Pitch, Yaw, Throttle, Arm commands |
| ESP32 → Laptop | UDP | 4212 | Receiving drone telemetry & battery voltage |
| Main Script → Test Runner | UDP | 4211 | Logging telemetry and command state to CSV |
| Mock Headset → Laptop | LSL | OpenBCI_Mock | 8-Channel 256Hz EEG stream simulation |

---

## 🧠 Frequency & Command Mapping

The system uses specific SSVEP frequencies mapped to drone actions. Critical commands are spaced 1Hz apart on the lower end, while directional commands are grouped on the higher end:

| Frequency | Command | Notes |
|-----------|---------|-------|
| **9.25 Hz** | TAKEOFF | Critical command (Spaced 1Hz) |
| **10.25 Hz**| STOP | Emergency kill switch |
| **11.25 Hz**| LAND | Critical command (Spaced 1Hz) |
| **12.75 Hz**| RIGHT | Directional movement |
| **13.75 Hz**| FORWARD | Directional movement |
| **14.25 Hz**| BACKWARD| Directional movement |
| **14.75 Hz**| LEFT | Directional movement |

*(Note: The bandpass filter is configured from 7.0Hz to 18.0Hz to cleanly capture this dataset).*

---

## 🛠️ Hardware & Software Requirements

### Hardware
* **Drone:** FPV drone running Betaflight v4.0+
* **Flight Controller:** Must support MSP over UART
* **Wireless Bridge:** ESP32 Dev Board (Soldered to drone's UART RX/TX)
* **Failsafe:** Physical RC Transmitter bound to the drone

### Software Dependencies

    pip install -r requirements.txt
    # Requires: sounddevice, scipy, vosk, pylsl, scikit-learn, numpy, keyboard

You will also need the **Vosk Small English Model** (vosk-model-small-en-us-0.15) extracted into the project root.

---

## 🚀 Pre-Flight Setup (Hardware)

**⚠️ CRITICAL: Remove the drone propellers before testing.**

### 1. Flash the ESP32
1. Open Arduino IDE and load ESP32/ESP32_Firmware.ino.
2. Update WIFI_SSID and WIFI_PASSWORD (or set WIFI_MODE to WIFI_SOFTAP for field use).
3. Flash to the ESP32 Dev Module.

### 2. Wire & Configure Betaflight
1. Solder ESP32 **TX (GPIO 17)** to a free **RX pad** on the Flight Controller. Power with 5V/GND.
2. In Betaflight Configurator -> **Ports** tab, enable **MSP** for that UART at **115200 baud**.
3. *Safety Note:* main_bci.py strictly sends UDP payloads as Roll, Pitch, Yaw, Throttle, Arm to perfectly match standard Betaflight MSP mapping.

---

## 🎮 How to Run the System

To test the full pipeline without flying a physical drone, you need to run two scripts.

### Step 1: Start the EEG Server
Open a terminal and start the mock LSL stream. This script loads the Nakanishi dataset into memory and broadcasts silence until you inject a command.

    python server.py

### Step 2: Start the Main Control Station
In a second terminal, start the drone controller. It will connect to the ESP32 (or fail gracefully if not connected) and start listening to the LSL stream and your microphone.

    python main_bci.py

### Step 3: Execute Fusion Commands
By default, the script runs in BOTH (Fusion) mode.
1. **Trigger EEG:** In the server.py terminal window, press a mapped key (e.g., W, A, S, D) to inject a 2-second burst of SSVEP brainwaves.
2. **Trigger Voice:** Immediately speak the corresponding command into your microphone (e.g., "Forward").
3. **Execution:** main_bci.py will correlate the voice command and the CCA-detected frequency. If they match, the command is sent to the drone.

---

## 📂 Directory Structure

    droneProject/
    ├── 📄 main_bci.py                 # Core OOP controller: DSP, voice, fusion, UDP
    ├── 📄 server.py                   # Mock EEG Server (Nakanishi Dataset -> LSL)
    ├── 📁 nakanishi_unfiltered_eeg/   # Pre-recorded SSVEP trials (.npy files)
    ├── 📁 ESP32/                      # Wireless bridge firmware (.ino)
    ├── 📁 vosk-model-small-en-us-0.15/# Offline speech recognition model
    ├── 📁 test/                       # Automated data collection framework
    └── 📄 requirements.txt            # Python dependencies

---

## ⚙️ Configuration & Tuning Guide

All tunable parameters have been centralized at the top of the DroneController.__init__ method in main_bci.py. Look for the ✏️ TUNE: comments.

### Key Tuning Variables:
* self.mode = ExperimentMode.BOTH: Change to VOICE_ONLY or EEG_ONLY to test individual modalities without needing simultaneous triggers.
* self.action_duration = 1.0: How long (in seconds) the drone moves before automatically returning to a neutral hover.
* self.enable_smoothing = True: Toggles between smooth cinematic ramping and instant aggressive RC adjustments.
* self.confidence_threshold = 0.50: The minimum CCA correlation score required to accept an EEG frequency. Raise this if you get false positives.
* self.target_rc_channels["throttle"]: Look inside apply_command() to set your drone's specific hover throttle (usually between 1400-1600).

---

## ⚠️ Troubleshooting & FAQs

**1. "Address already in use" Error on Port 4210/4212**
Ensure no other instances of main_bci.py are running in the background.

**2. LSL Stream Not Found**
Ensure server.py is running *before* main_bci.py. The script specifically looks for name='OpenBCI_Mock'.

**3. Voice Recognition is ignoring me**
Make sure your microphone is set as the default system recording device. You can lower VOICE_CONFIDENCE_THRESHOLD or adjust the COMMAND_EXPIRY_SECONDS to give yourself a wider window to match the EEG signal.

**4. Drone spins wildly or shoots up into the air**
Double-check your channel mapping in Betaflight. main_bci.py sends Roll, Pitch, Yaw, Throttle. If your Betaflight is configured to expect TAER instead of AETR, you must change the Channel Map in the Betaflight Receiver tab to match AETR.
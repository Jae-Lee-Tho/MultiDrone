# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multimodal Brain-Computer Interface (BCI) drone controller that fuses **SSVEP EEG** and **voice commands** to fly a Betaflight FPV drone. The system uses the Nakanishi SSVEP dataset (pre-recorded brainwave data) as a mock EEG headset for reliable field testing.

## Running the System

**Automated launcher (recommended):**
```bash
python start.py
```
This opens two terminals: one for the Node.js ESP32 simulator and one for the Python ground control station.

**Manual startup (two terminals required):**

Terminal 1 — Virtual ESP32/Betaflight simulator:
```bash
node ESP32/ESP32_Firmware.js
```

Terminal 2 — Mock EEG server (run from OPEN_BCI directory):
```bash
cd OPEN_BCI
python eeg_server.py
```

Terminal 3 — Ground control station (run from Raspberry_Pi directory):
```bash
cd Raspberry_Pi
python Raspberry_Pi.py
```

**Data collection / test runner:**
```bash
cd test
python test_runner.py
```

**RC calibration wizard** (requires live ESP32):
```bash
python Tools/calibrate_rc.py
```

**Python environment:**
```bash
pip install -r requirements.txt
# or with uv (pyproject.toml present):
uv sync
```

## Architecture

The system is composed of three concurrent processes communicating over UDP and LSL:

```
[OPEN_BCI/eeg_server.py]  ──(LSL: OpenBCI_Mock)──>  [Raspberry_Pi/Raspberry_Pi.py]
[Microphone]               ──(sounddevice)──────────> [Raspberry_Pi/Raspberry_Pi.py]
                                                              │
                                                       (UDP :4210)
                                                              │
                                                              v
                                                  [ESP32/ESP32_Firmware.js]
                                                              │
                                                       (UDP :4212 telemetry back)
                                                              │
                                                              v
                                                  [test/test_runner.py]  (UDP :4211)
```

### Port Map
| Port | Direction | Purpose |
|------|-----------|---------|
| 4210 | Laptop → ESP32 | RC channels: Roll,Pitch,Yaw,Throttle,Arm |
| 4211 | Laptop → Test Runner | Unified telemetry + command state |
| 4212 | ESP32 → Laptop | Betaflight telemetry (attitude, analog, RC) |

### Key Files

- **`Raspberry_Pi/Raspberry_Pi.py`** — The main ground control station. Contains the `DroneController` class with all EEG/DSP, voice recognition, fusion logic, and UDP command output. This is the central coordinator.
- **`OPEN_BCI/eeg_server.py`** — Mock EEG headset. Loads Nakanishi dataset `.npy` files and broadcasts them over LSL at 256 Hz. Press keys (W/A/S/D/T/L/Q) to inject 2-second SSVEP bursts.
- **`ESP32/ESP32_Firmware.js`** — Virtual Betaflight flight controller simulator. Includes physics engine, failsafe watchdog (500ms timeout), and telemetry broadcaster.
- **`ESP32/ESP32_Firmware.ino`** — Real firmware to flash onto physical ESP32 hardware.

### EEG Signal Pipeline (inside `DroneController`)

1. LSL stream pulled in `eeg_polling_thread` → 2-second sliding window buffer
2. `_preprocess_eeg`: detrend → 60Hz notch → 7–18Hz bandpass → Common Average Reference (CAR)
3. `analyze_ssvep_window`: CCA against sine/cosine reference signals at each of 7 target frequencies
4. Best CCA correlation score compared against `confidence_threshold` (default 0.65)
5. On detection: buffer flushed entirely (2-second cooldown to prevent re-triggering)

### Fusion Logic (BOTH mode)

Voice command and EEG command must **agree** within `command_expiry_seconds` (default 2.5s). Mismatches are discarded. STOP/emergency commands from either modality always execute immediately.

### SSVEP Frequency → Command Mapping

Defined in `FREQ_TO_COMMAND` at the top of `Raspberry_Pi.py` and mirrored in `eeg_server.py`:

| Frequency | Command | Server Key |
|-----------|---------|------------|
| 9.25 Hz | TAKEOFF | T |
| 10.25 Hz | STOP | Q |
| 11.25 Hz | LAND | L |
| 12.75 Hz | RIGHT | D |
| 13.75 Hz | FORWARD | W |
| 14.25 Hz | BACKWARD | S |
| 14.75 Hz | LEFT | A |

## Key Tuning Parameters

All tunable parameters are centralized at the top of `DroneController.__init__()` in `Raspberry_Pi/Raspberry_Pi.py`, marked with `✏️ TUNE:` comments:

- `self.mode` — Switch between `VOICE_ONLY`, `EEG_ONLY`, `BOTH`, `PHYSICAL_RC`
- `self.esp32_ip` — Must match the ESP32's actual Wi-Fi IP (`192.168.4.1` for SoftAP mode)
- `self.confidence_threshold` — CCA score cutoff (raise to reduce false positives)
- `self.action_duration` — How long a movement command persists before auto-stopping
- `self.target_rc_channels["throttle"]` in `apply_command()` — Hover throttle (find via `calibrate_rc.py`)

## Important Constraints

- **Vosk model path**: `Raspberry_Pi.py` looks for `vosk-model-small-en-us-0.15` relative to its working directory. The model must be at `Raspberry_Pi/vosk-model-small-en-us-0.15/`.
- **EEG data path**: `eeg_server.py` looks for `nakanishi_unfiltered_eeg/subject_8/` relative to its working directory, so it must run from `OPEN_BCI/`.
- **Start order**: `eeg_server.py` must be running before `Raspberry_Pi.py` (LSL stream must exist on connection).
- **Betaflight channel order**: The UDP payload is Roll, Pitch, Yaw, Throttle, Arm (AETR). If the physical Betaflight is configured as TAER, change the Channel Map in the Receiver tab.
- **Propeller safety**: Always remove propellers before any software testing.

# Multimodal UAV Control — Experiment Data Logger

This system collects per-trial data for a symposium experiment comparing three drone
control methods: voice-only, SSVEP-only, and voice+SSVEP multimodal fusion.

---

## Installation

### 1. Install pyserial (required for Betaflight telemetry)

```bash
pip install pyserial
```

Or if you're using the project's `uv` environment:

```bash
uv add pyserial
```

> The experiment runner works without pyserial — it falls back to dummy RC values
> so you can still collect manual data when Betaflight is not connected.

---

## Finding Your Mac Serial Port

Plug in your flight controller via USB, then run:

```bash
ls /dev/cu.*
```

Look for something like:
```
/dev/cu.usbmodem0x80000001
/dev/cu.usbmodem14301
```

Open `betaflight_msp.py` and update the `SERIAL_PORT` constant at the top:

```python
SERIAL_PORT = "/dev/cu.usbmodem14301"   # ← your port here
```

Also make sure MSP is enabled in Betaflight Configurator:
`Ports tab → your USB UART → enable MSP`

---

## Running the Experiment

```bash
cd /path/to/droneProject
python run_experiment.py
```

The script will:
1. Ask you to select a mode (voice_only / ssvep_only / voice_ssvep)
2. Loop through trials until you type `quit`
3. Save one row to `experiment_results.csv` per trial

Each trial asks for:
- The **target command** the pilot was supposed to execute
- The **predicted command(s)** from voice / SSVEP (entered manually for now)
- The **confidence scores** (0.0–1.0) for each modality
- Whether the drone behaved correctly (hardware check)
- Optional free-text notes

---

## CSV Column Reference

| Column | Type | Description |
|--------|------|-------------|
| `trial_id` | int | Auto-incrementing ID that persists across sessions |
| `timestamp` | ISO string | When the row was written (e.g. `2026-05-10T14:32:05.123`) |
| `mode` | string | `voice_only`, `ssvep_only`, or `voice_ssvep` |
| `target_command` | string | The command the pilot intended to execute |
| `voice_prediction` | string | What the voice model recognised |
| `ssvep_prediction` | string | What the SSVEP/CCA decoder detected |
| `voice_confidence` | float | Confidence score from the voice model (0–1) |
| `ssvep_confidence` | float | Confidence/CCA score from the SSVEP decoder (0–1) |
| `voice_ssvep_match` | bool / N/A | `True` if both predictions agreed; `N/A` in single-modality modes |
| `decision` | string | `EXECUTE` or `BLOCK` |
| `executed_command` | string | The command actually sent, or `NONE` if blocked |
| `command_sent_time` | ISO string | Timestamp when the command was dispatched |
| `drone_response_time` | ISO string | Timestamp after the drone response was read |
| `latency_sec` | float | Seconds between command send and response read |
| `rc_roll_before` | int | Roll RC channel value (1000–2000) before command |
| `rc_pitch_before` | int | Pitch RC channel value before command |
| `rc_yaw_before` | int | Yaw RC channel value before command |
| `rc_throttle_before` | int | Throttle RC channel value before command |
| `rc_roll_after` | int | Roll RC channel value after command |
| `rc_pitch_after` | int | Pitch RC channel value after command |
| `rc_yaw_after` | int | Yaw RC channel value after command |
| `rc_throttle_after` | int | Throttle RC channel value after command |
| `betaflight_armed` | bool | Whether the FC was armed at command time |
| `is_correct` | bool | `True` if the executed command matched the target (or block was intended) |
| `wrong_command_executed` | bool | `True` if a command executed but didn't match the target |
| `blocked` | bool | `True` if the command was suppressed by the fusion rule |
| `hardware_misrecognized` | bool | `True` if drone behaviour differed from the sent command |
| `notes` | string | Free-text observations for the trial |

---

## Mode Descriptions

### voice_only
- Only voice recognition is used.
- `executed_command = voice_prediction` always.
- No cross-validation — higher risk of false positives from noise.

### ssvep_only
- Only SSVEP/CCA is used.
- `executed_command = ssvep_prediction` always.
- No cross-validation — susceptible to EEG artifacts.

### voice_ssvep (multimodal fusion)
- Both modalities must predict the **same** command.
- If they agree → `EXECUTE`.
- If they disagree → `BLOCK` (no command sent).
- This is the safety-critical mode: a false positive in one modality cannot
  cause an unintended command on its own.

---

## Symposium Metrics — How to Compute Them

Once `experiment_results.csv` has been collected, compute these with pandas or
the standard `csv` module. All metrics are per-mode comparisons.

### Command Accuracy
> "Of the executed commands, what fraction matched the target?"

```
accuracy = rows where is_correct=True AND blocked=False
           ─────────────────────────────────────────────
           rows where blocked=False
```

### False Command Execution Rate
> "What fraction of executed commands were the wrong command?"

```
false_exec_rate = rows where wrong_command_executed=True
                  ─────────────────────────────────────
                  total rows
```

### Agreement Rate (voice_ssvep only)
> "How often did voice and SSVEP predict the same command?"

```
agreement_rate = rows where voice_ssvep_match=True
                 ──────────────────────────────────
                 rows in voice_ssvep mode
```

### Blocked Command Rate
> "What fraction of trials were suppressed by the fusion rule?"

```
blocked_rate = rows where blocked=True
               ───────────────────────
               total rows
```

### Average Latency

```
mean_latency = mean(latency_sec) per mode
```

### Confusion Matrix
Cross-tabulate `target_command` (rows) against `executed_command` (columns)
for each mode separately. Blocked trials map `executed_command = NONE` and
appear as a separate column.

---

## Connecting Real Modules (future)

| Module | File to edit | What to change |
|--------|-------------|----------------|
| Voice (Vosk) | `run_experiment.py` | Replace `prompt_prediction("voice")` with a call to your Vosk recogniser |
| SSVEP (CCA) | `run_experiment.py` | Replace `prompt_prediction("ssvep")` with a call to `analyze_ssvep_window()` |
| ESP32 UDP | `run_experiment.py` | Fill in `send_command_to_drone()` with a `socket.sendto()` call |
| Betaflight MSP | `betaflight_msp.py` | Update `SERIAL_PORT` constant at the top of the file |

"""
run_experiment.py

Interactive terminal runner for the multimodal UAV control experiment.
Supports three modes: voice_only, ssvep_only, voice_ssvep.

Usage:
    python run_experiment.py

Type 'quit' at any command prompt to end the session.
"""

import time
import socket
import json
from experiment_logger import ExperimentLogger
from betaflight_msp import BetaflightMSP

# ── Configuration ─────────────────────────────────────────────────────────────
CSV_OUTPUT     = "experiment_results.csv"
VALID_MODES    = ["voice_only", "ssvep_only", "voice_ssvep"]
VALID_COMMANDS = ["forward", "backward", "left", "right", "up", "down", "stop"]
# ─────────────────────────────────────────────────────────────────────────────


# =============================================================================
# PLACEHOLDER — replace with real drone comms when hardware is ready
# =============================================================================

def send_command_to_drone(command: str) -> None:
    """
    Simulates sending a command to the drone over UDP to the ESP32.

    TODO: Replace the print statement with real UDP logic, e.g.:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(command.upper().encode(), ("192.168.4.1", 4210))
    """
    print(f"\n  [DRONE] >>> Sending command: {command.upper()}")


# =============================================================================
# INPUT HELPERS
# =============================================================================

def pick_mode() -> str:
    """Prompt the user to choose an experiment mode. Returns the mode string."""
    print("\nSelect experiment mode:")
    for i, m in enumerate(VALID_MODES, 1):
        print(f"  {i}. {m}")
    while True:
        raw = input("Enter number or name: ").strip().lower()
        if raw in VALID_MODES:
            return raw
        if raw in {"1", "2", "3"}:
            return VALID_MODES[int(raw) - 1]
        print("  Invalid — enter 1, 2, 3, or the mode name.")


def prompt_command(label: str) -> str:
    """
    Ask the user for a command name.
    Returns the command string, or 'quit' to end the session.
    """
    options = " / ".join(VALID_COMMANDS) + " / quit"
    while True:
        raw = input(f"\n  {label} ({options}): ").strip().lower()
        if raw == "quit":
            return "quit"
        if raw in VALID_COMMANDS:
            return raw
        print(f"    Invalid. Choose from: {', '.join(VALID_COMMANDS)}")


def prompt_confidence(label: str) -> float:
    """Ask the user for a confidence score between 0.0 and 1.0."""
    while True:
        try:
            val = float(input(f"  {label} confidence (0.0–1.0): ").strip())
            if 0.0 <= val <= 1.0:
                return val
            print("    Enter a value between 0.0 and 1.0.")
        except ValueError:
            print("    Enter a decimal number, e.g. 0.87")


def prompt_prediction(modality: str) -> tuple[str, float]:
    """
    Ask for both the predicted command and confidence for a given modality.
    Returns ("quit", 0.0) if the user wants to exit.
    """
    print(f"\n  [{modality.upper()} input]")
    predicted = prompt_command(f"    {modality} prediction")
    if predicted == "quit":
        return "quit", 0.0
    confidence = prompt_confidence(f"    {modality}")
    return predicted, confidence


def prompt_yes_no(question: str) -> bool:
    """Ask a yes/no question and return True for yes, False for no."""
    while True:
        raw = input(f"  {question} (yes/no): ").strip().lower()
        if raw in ("yes", "y"):
            return True
        if raw in ("no", "n"):
            return False
        print("    Please type yes or no.")


# =============================================================================
# DECISION ENGINE
# =============================================================================

def apply_decision(
    mode: str,
    voice_pred: str,
    ssvep_pred: str,
) -> tuple[str, str, bool, str]:
    """
    Apply the fusion rule for the selected mode.

    Returns
    -------
    decision          : "EXECUTE" or "BLOCK"
    executed_command  : the command string, or "NONE" if blocked
    blocked           : True when the command was suppressed
    voice_ssvep_match : "True", "False", or "N/A" (single-modality modes)
    """
    if mode == "voice_only":
        return "EXECUTE", voice_pred, False, "N/A"

    if mode == "ssvep_only":
        return "EXECUTE", ssvep_pred, False, "N/A"

    # ── voice_ssvep fusion: both modalities must agree ──────────────────────
    match = (voice_pred == ssvep_pred)
    if match:
        return "EXECUTE", voice_pred, False, "True"
    else:
        return "BLOCK", "NONE", True, "False"


# =============================================================================
# SINGLE TRIAL
# =============================================================================

def run_trial(
    trial_id: int,
    mode: str,
    logger: ExperimentLogger,
    msp: BetaflightMSP,
) -> bool:
    """
    Run one complete trial.
    Returns True to continue, False if the user typed 'quit'.
    """
    print(f"\n{'═' * 52}")
    print(f"  Trial #{trial_id:03d}  |  Mode: {mode}")
    print(f"{'═' * 52}")

    # ── 1. Target command ────────────────────────────────────────────────────
    target = prompt_command("Target command")
    if target == "quit":
        return False

    # ── 2. Modality predictions ──────────────────────────────────────────────
    voice_pred:  str   = "N/A"
    voice_conf:  float = 0.0
    ssvep_pred:  str   = "N/A"
    ssvep_conf:  float = 0.0

    if mode in ("voice_only", "voice_ssvep"):
        voice_pred, voice_conf = prompt_prediction("voice")
        if voice_pred == "quit":
            return False

    if mode in ("ssvep_only", "voice_ssvep"):
        ssvep_pred, ssvep_conf = prompt_prediction("ssvep")
        if ssvep_pred == "quit":
            return False

    # ── 3. RC snapshot BEFORE command ────────────────────────────────────────
    print("\n  [Betaflight] Reading RC channels — BEFORE command...")
    rc_before = msp.read_rc()
    print(
        f"    Roll={rc_before['rc_roll']}  Pitch={rc_before['rc_pitch']}  "
        f"Yaw={rc_before['rc_yaw']}  Throttle={rc_before['rc_throttle']}  "
        f"Armed={rc_before['armed']}"
    )

    # ── 4. Decision ──────────────────────────────────────────────────────────
    decision, executed_command, blocked, voice_ssvep_match = apply_decision(
        mode, voice_pred, ssvep_pred
    )

    print(f"\n  [Decision] → {decision}")
    if blocked:
        print(
            f"    ⛔  BLOCKED — voice='{voice_pred}' ≠ ssvep='{ssvep_pred}'\n"
            f"        Command suppressed. No signal sent to drone."
        )
    else:
        print(f"    ✅  EXECUTE — '{executed_command.upper()}'")

    # ── 5. Send command + measure latency ────────────────────────────────────
    command_sent_time = logger.now_iso()
    t0 = time.perf_counter()

    if not blocked:
        send_command_to_drone(executed_command)

    t1 = time.perf_counter()
    drone_response_time = logger.now_iso()
    latency_sec = round(t1 - t0, 6)

    # ── 6. RC snapshot AFTER command ─────────────────────────────────────────
    print("\n  [Betaflight] Reading RC channels — AFTER command...")
    rc_after = msp.read_rc()
    print(
        f"    Roll={rc_after['rc_roll']}  Pitch={rc_after['rc_pitch']}  "
        f"Yaw={rc_after['rc_yaw']}  Throttle={rc_after['rc_throttle']}  "
        f"Armed={rc_after['armed']}"
    )

    # ── 7. Correctness evaluation ────────────────────────────────────────────
    if blocked:
        # Ask whether blocking was the intended outcome for this specific trial.
        # e.g. a trial deliberately designed to verify the safety block works.
        block_was_expected = prompt_yes_no(
            "\n  Was a BLOCK the expected/correct outcome for this trial?"
        )
        is_correct            = block_was_expected
        wrong_command_executed = False
    else:
        is_correct             = (executed_command == target)
        wrong_command_executed = (executed_command != target)

    # ── 8. Hardware misrecognition ───────────────────────────────────────────
    print()
    hardware_misrecognized = prompt_yes_no(
        "Did the drone behave differently than the command sent? (hardware misrecognized)"
    )

    # ── 9. Optional notes ────────────────────────────────────────────────────
    notes_raw = input("  Notes (press Enter to skip): ").strip()
    notes     = notes_raw if notes_raw else "N/A"

    # ── 10. Save row ─────────────────────────────────────────────────────────
    row: dict = {
        "trial_id":              trial_id,
        "timestamp":             logger.now_iso(),
        "mode":                  mode,
        "target_command":        target,
        "voice_prediction":      voice_pred,
        "ssvep_prediction":      ssvep_pred,
        "voice_confidence":      voice_conf  if voice_pred  != "N/A" else "N/A",
        "ssvep_confidence":      ssvep_conf  if ssvep_pred  != "N/A" else "N/A",
        "voice_ssvep_match":     voice_ssvep_match,
        "decision":              decision,
        "executed_command":      executed_command,
        "command_sent_time":     command_sent_time,
        "drone_response_time":   drone_response_time,
        "latency_sec":           latency_sec,
        "rc_roll_before":        rc_before["rc_roll"],
        "rc_pitch_before":       rc_before["rc_pitch"],
        "rc_yaw_before":         rc_before["rc_yaw"],
        "rc_throttle_before":    rc_before["rc_throttle"],
        "rc_roll_after":         rc_after["rc_roll"],
        "rc_pitch_after":        rc_after["rc_pitch"],
        "rc_yaw_after":          rc_after["rc_yaw"],
        "rc_throttle_after":     rc_after["rc_throttle"],
        "betaflight_armed":      rc_before["armed"],
        "is_correct":            is_correct,
        "wrong_command_executed": wrong_command_executed,
        "blocked":               blocked,
        "hardware_misrecognized": hardware_misrecognized,
        "notes":                 notes,
    }
    logger.log_trial(row)

    # ── 11. Summary ──────────────────────────────────────────────────────────
    status_icon = "✅" if is_correct else ("⛔" if blocked else "❌")
    print(
        f"\n  {status_icon} Trial #{trial_id:03d} saved — "
        f"correct={is_correct}  blocked={blocked}  latency={latency_sec:.4f}s"
    )
    return True


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    print("=" * 52)
    print("   MULTIMODAL UAV CONTROL — EXPERIMENT LOGGER")
    print("=" * 52)

    mode   = pick_mode()
    logger = ExperimentLogger(filepath=CSV_OUTPUT)
    msp    = BetaflightMSP()

    # Determine the next trial ID (continues across sessions)
    trial_id = logger.count_trials() + 1

    print(f"\n  Mode        : {mode}")
    print(f"  Output file : {CSV_OUTPUT}")
    print(f"  First trial : #{trial_id:03d}")
    print(f"\n  Type 'quit' at any command prompt to end the session.\n")

    try:
        while True:
            keep_going = run_trial(trial_id, mode, logger, msp)
            if not keep_going:
                break
            trial_id += 1
    except KeyboardInterrupt:
        print("\n\n  [Interrupted] Ctrl+C received.")
    finally:
        msp.close()
        saved = logger.count_trials()
        print(f"\n{'=' * 52}")
        print(f"  Session ended. Total trials in file: {saved}")
        print(f"  Results saved to: {CSV_OUTPUT}")
        print("=" * 52)


if __name__ == "__main__":
    main()

"""
experiment_logger.py

Reusable CSV logger for the multimodal UAV control experiment.
Creates the file with headers on first use; appends on subsequent runs.
"""

import csv
import os
from datetime import datetime
from typing import Any

# Every column in the exact order they appear in the CSV.
COLUMNS: list[str] = [
    "trial_id",
    "timestamp",
    "mode",
    "target_command",
    "voice_prediction",
    "ssvep_prediction",
    "voice_confidence",
    "ssvep_confidence",
    "voice_ssvep_match",
    "decision",
    "executed_command",
    "command_sent_time",
    "drone_response_time",
    "latency_sec",
    "rc_roll_before",
    "rc_pitch_before",
    "rc_yaw_before",
    "rc_throttle_before",
    "rc_roll_after",
    "rc_pitch_after",
    "rc_yaw_after",
    "rc_throttle_after",
    "betaflight_armed",
    "is_correct",
    "wrong_command_executed",
    "blocked",
    "hardware_misrecognized",
    "notes",
]


class ExperimentLogger:
    """
    Writes one CSV row per trial to `filepath`.

    Usage:
        logger = ExperimentLogger("experiment_results.csv")
        logger.log_trial({"trial_id": 1, "mode": "voice_only", ...})
    """

    def __init__(self, filepath: str = "experiment_results.csv") -> None:
        self.filepath = filepath
        self._ensure_headers()

    # ── File management ──────────────────────────────────────────────────────

    def _ensure_headers(self) -> None:
        """Write the header row only if the file does not exist yet."""
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=COLUMNS).writeheader()
            print(f"[Logger] Created new results file: {self.filepath}")
        else:
            print(f"[Logger] Appending to existing file: {self.filepath}")

    # ── Writing ──────────────────────────────────────────────────────────────

    def log_trial(self, data: dict[str, Any]) -> None:
        """
        Append one row to the CSV.
        Any column not present in `data` defaults to "N/A".
        """
        row = {col: data.get(col, "N/A") for col in COLUMNS}
        with open(self.filepath, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def now_iso() -> str:
        """Return the current time as a human-readable ISO 8601 string."""
        return datetime.now().isoformat(timespec="milliseconds")

    def count_trials(self) -> int:
        """Return the number of data rows already saved (excludes header)."""
        if not os.path.exists(self.filepath):
            return 0
        with open(self.filepath, "r", newline="", encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)  # subtract the header line

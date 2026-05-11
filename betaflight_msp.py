"""
betaflight_msp.py

Reads RC channel values and armed state from a Betaflight flight controller
over USB serial using the MSP v1 (MultiWii Serial Protocol).

─── Changing the serial port ────────────────────────────────────────────────
Set SERIAL_PORT below to match your FC's USB port.

  macOS — find it with:   ls /dev/cu.*
    e.g.  /dev/cu.usbmodem0x80000001
          /dev/cu.usbmodem14301

  Linux — find it with:   ls /dev/tty*
    e.g.  /dev/ttyUSB0
          /dev/ttyACM0

  Windows — check Device Manager → Ports (COM & LPT)
    e.g.  COM3

Also make sure MSP is enabled in Betaflight Configurator:
  Ports tab → the UART your FC exposes over USB → enable MSP.
─────────────────────────────────────────────────────────────────────────────

If the FC is not connected, every read returns safe fallback values so the
experiment runner still works for manual / offline data collection.
"""

import struct
import time
from typing import Optional

# ── ✏️ Change this to your FC's serial port ───────────────────────────────
SERIAL_PORT = "/dev/cu.usbmodem0x80000001"
BAUD_RATE   = 115200
# ─────────────────────────────────────────────────────────────────────────────

# MSP v1 command codes used here
_MSP_RC       = 105   # RC channels (up to 16 × uint16)
_MSP_STATUS   = 101   # Flight mode bitmask + cycle time + armed state
_MSP_ATTITUDE = 108   # Roll / pitch / heading angles (unused by default, available)

# Returned whenever the FC is offline or a read fails
FALLBACK: dict = {
    "rc_roll":     1500,
    "rc_pitch":    1500,
    "rc_yaw":      1500,
    "rc_throttle": 1000,
    "armed":       False,
}

# Try to import pyserial; if it's missing, every read silently returns fallback
try:
    import serial as _serial_module
    _PYSERIAL_OK = True
except ImportError:
    _PYSERIAL_OK = False
    print(
        "[MSP] pyserial is not installed.\n"
        "      Run:  pip install pyserial\n"
        "      Continuing in offline mode — all RC values will be fallback defaults.\n"
    )


class BetaflightMSP:
    """
    Communicates with Betaflight over USB via MSP v1.

    Channel mapping (configured for the index order used in this project):
        channels[0] → rc_roll
        channels[1] → rc_pitch
        channels[2] → rc_yaw
        channels[3] → rc_throttle

    Note: Standard Betaflight AETR puts throttle at index 2 and rudder at 3.
    If your FC uses strict AETR, swap the index assignments inside read_rc().
    """

    def __init__(self, port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
        self.port = port
        self.baud = baud
        self._ser: Optional[object] = None  # serial.Serial instance, or None
        self._connect()

    # ── Connection ───────────────────────────────────────────────────────────

    def _connect(self) -> None:
        if not _PYSERIAL_OK:
            return
        try:
            self._ser = _serial_module.Serial(
                self.port,
                self.baud,
                timeout=0.5,        # per-byte read timeout
                write_timeout=0.5,
            )
            time.sleep(0.1)         # let the USB-serial converter settle
            print(f"[MSP] Connected to Betaflight on {self.port} @ {self.baud} baud.")
        except Exception as exc:
            print(f"[MSP] Could not open {self.port}: {exc}")
            print("[MSP] Continuing in offline mode — RC values will be fallback defaults.\n")
            self._ser = None

    def close(self) -> None:
        """Release the serial port cleanly."""
        if self._ser is not None and self._ser.is_open:  # type: ignore[union-attr]
            self._ser.close()  # type: ignore[union-attr]
            print("[MSP] Serial port closed.")

    # ── Low-level MSP v1 framing ─────────────────────────────────────────────

    @staticmethod
    def _build_request(cmd: int) -> bytes:
        """
        Build a MSP v1 request frame with no payload.

        Frame layout:  $ M < [size=0x00] [cmd] [checksum]
        Checksum:      XOR of all bytes after the direction char.
                       With empty payload: checksum = 0x00 XOR cmd = cmd.
        """
        return bytes([0x24, 0x4D, 0x3C, 0x00, cmd, cmd])

    def _read_response(self, expected_cmd: int) -> Optional[bytes]:
        """
        Send one MSP request and return the raw response payload bytes.
        Returns None on any error (timeout, bad checksum, wrong command, etc.).
        """
        if self._ser is None:
            return None

        try:
            self._ser.reset_input_buffer()                       # type: ignore[union-attr]
            self._ser.write(self._build_request(expected_cmd))   # type: ignore[union-attr]

            # Scan the incoming byte stream for the response preamble "$M>"
            window = bytearray()
            for _ in range(200):           # give up after 200 bytes
                raw = self._ser.read(1)    # type: ignore[union-attr]
                if not raw:
                    return None            # read timeout
                window.extend(raw)
                if window[-3:] == bytearray(b"$M>"):
                    break
            else:
                return None                # preamble never appeared

            # Read [size][cmd]
            header = self._ser.read(2)     # type: ignore[union-attr]
            if len(header) < 2:
                return None
            size, cmd = header[0], header[1]
            if cmd != expected_cmd:
                return None                # wrong response (stale data)

            # Read [payload (size bytes)] + [checksum (1 byte)]
            body = self._ser.read(size + 1)  # type: ignore[union-attr]
            if len(body) < size + 1:
                return None

            payload       = body[:size]
            checksum_byte = body[size]

            # Verify checksum: XOR of size, cmd, and all payload bytes
            chk = size ^ cmd
            for b in payload:
                chk ^= b
            if chk != checksum_byte:
                return None

            return bytes(payload)

        except Exception as exc:
            print(f"[MSP] Read error: {exc}")
            return None

    # ── Public API ───────────────────────────────────────────────────────────

    def read_rc(self) -> dict:
        """
        Return RC channel values and armed state.
        Falls back to neutral/safe values when the FC is offline.

        Return keys:
            rc_roll (int)     — 1000–2000
            rc_pitch (int)    — 1000–2000
            rc_yaw (int)      — 1000–2000
            rc_throttle (int) — 1000–2000
            armed (bool)
        """
        payload = self._read_response(_MSP_RC)

        if payload is None or len(payload) < 8:
            return FALLBACK.copy()

        # Each RC channel is a uint16 (little-endian).
        n = len(payload) // 2
        channels = struct.unpack(f"<{n}H", payload[: n * 2])

        return {
            "rc_roll":     int(channels[0]) if n > 0 else 1500,
            "rc_pitch":    int(channels[1]) if n > 1 else 1500,
            "rc_yaw":      int(channels[2]) if n > 2 else 1500,
            "rc_throttle": int(channels[3]) if n > 3 else 1000,
            "armed":       self._read_armed(),
        }

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _read_armed(self) -> bool:
        """
        Read MSP_STATUS (cmd 101) and extract the ARM flag.

        MSP_STATUS payload layout (11 bytes):
            cycleTime     uint16  (2 bytes)
            i2cErrors     uint16  (2 bytes)
            activeSensors uint16  (2 bytes)
            mode          uint32  (4 bytes)  ← bitmask of active flight modes
            currentProfile uint8 (1 byte)

        In Betaflight 4.x, the ARM mode is box ID 0, which sets bit 0 of `mode`.
        If this returns wrong results, check your Betaflight version's box ID mapping.
        """
        payload = self._read_response(_MSP_STATUS)
        if payload is None or len(payload) < 11:
            return False
        _, _, _, mode, _ = struct.unpack("<HHHIB", payload[:11])
        return bool(mode & 0x01)   # bit 0 = ARM

    def read_attitude(self) -> dict:
        """
        Optional: read roll/pitch/heading angles from MSP_ATTITUDE (cmd 108).
        Returns zeros if the FC is offline.

        MSP_ATTITUDE payload (6 bytes):
            angx  int16  — roll  angle × 10  (degrees × 10)
            angy  int16  — pitch angle × 10
            heading int16 — compass heading (degrees, 0–359)
        """
        payload = self._read_response(_MSP_ATTITUDE)
        if payload is None or len(payload) < 6:
            return {"roll_angle": 0.0, "pitch_angle": 0.0, "heading": 0}
        angx, angy, heading = struct.unpack("<hhh", payload[:6])
        return {
            "roll_angle":  angx / 10.0,
            "pitch_angle": angy / 10.0,
            "heading":     heading,
        }

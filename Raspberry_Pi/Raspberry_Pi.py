# =============================================================================
# DRONE GROUND CONTROL STATION — LAPTOP (VOICE + MOCK EEG FUSION)
# =============================================================================

import os
import socket
import time
import threading
import json
import datetime
import numpy as np
import csv
from enum import Enum

import sounddevice as sd
from scipy.signal import butter, sosfiltfilt, iirnotch, detrend
from vosk import Model, KaldiRecognizer
from pylsl import resolve_byprop, StreamInlet
from sklearn.cross_decomposition import CCA


# =============================================================================
# SECTION 1 — CONFIGURATION & MAPPING
# =============================================================================

class ExperimentMode(Enum):
    VOICE_ONLY  = "VOICE_ONLY"
    EEG_ONLY    = "EEG_ONLY"
    BOTH        = "BOTH"
    PHYSICAL_RC = "PHYSICAL_RC"

class Command(Enum):
    TAKEOFF  = "TAKEOFF"
    LAND     = "LAND"
    FORWARD  = "FORWARD"
    BACKWARD = "BACKWARD"
    LEFT     = "LEFT"
    RIGHT    = "RIGHT"
    STOP     = "STOP"

# ✏️ TUNE: FREQUENCY MAPPING (Nakanishi Dataset)
FREQ_TO_COMMAND = {
     9.25: Command.TAKEOFF,
    10.25: Command.STOP,
    11.25: Command.LAND,
    12.75: Command.RIGHT,
    13.75: Command.FORWARD,
    14.25: Command.BACKWARD,
    14.75: Command.LEFT,
}

class DroneState(Enum):
    GROUNDED = "GROUNDED"
    AIRBORNE = "AIRBORNE"


# =============================================================================
# SECTION 2 — DRONE CONTROLLER CLASS
# =============================================================================

class DroneController:
    def __init__(self):
        # ---------------------------------------------------------------------
        # 🛠️ TUNABLE PARAMETERS (Adjust these to change system behavior)
        # ---------------------------------------------------------------------

        # --- CSV Data Logging ---
        self.csv_filename = f"'/Users/jaelee/Desktop/Drone_Trial - Sheet1.csv'
        with open(self.csv_filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Time", "Mode", "Voice_Pred", "CCA_Score", "EEG_Cmd", "Final_Cmd", "Voice_Recog_Time_s", "Drone_Recog_Time_s"])

        # --- General Experiment Settings ---
        self.mode = ExperimentMode.VOICE_ONLY   # ✏️ TUNE: Switch between VOICE_ONLY, EEG_ONLY, BOTH, PHYSICAL_RC

        # --- Drone Movement Dynamics ---
        self.action_duration = 1.0            
        self.enable_smoothing = True          
        self.smoothing_factor = 0.10          

        # --- Fusion Mode Timing ---
        self.command_expiry_seconds = 2.5     

        # --- Network Settings ---
        self.esp32_ip = "192.168.4.1"           # ✏️ TUNE/REQUIRED: Change this to the actual Wi-Fi IP address printed by your ESP32

        # --- EEG/SSVEP Signal Processing ---
        self.window_seconds = 2.0             
        self.window_step_fraction = 0.5       
        self.confidence_threshold = 0.65      
        self.num_harmonics = 3                
        self.notch_freq_hz = 60.0             

        # --- Latency & Voice Tracking ---
        self.speech_onset_time = 0.0        # 소리가 감지되기 시작한 절대 시간
        self.audio_threshold = 300          # ✏️ TUNE: 주변 소음에 맞춰 100~500 조절
        self.last_voice_latency = 0.0       # Vosk가 단어를 인식하는 데 걸린 시간
        self.pending_telemetry_cmd = None   # 드론 텔레메트리 피드백 대기용 명령
        self.pending_csv_data = None        # 텔레메트리 도착 시 기록할 임시 데이터

        # Filters 
        self.bandpass_low_hz = 7.0            
        self.bandpass_high_hz = 18.0          


        # ---------------------------------------------------------------------
        # ⚙️ INTERNAL STATE & CONSTANTS (Leave these alone)
        # ---------------------------------------------------------------------

        self.esp32_port = 4210
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.test_runner_ip = "127.0.0.1"
        self.test_runner_port = 4211
        self.test_runner_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.telemetry_port = 4212
        self.telemetry_rx_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.telemetry_rx_socket.settimeout(1.0)
        self.telemetry_rx_socket.bind(("0.0.0.0", self.telemetry_port))

        self.log_filename = f"flight_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

        self.drone_state = DroneState.GROUNDED
        self.is_moving = False
        self.last_movement_time = 0.0

        self.active_voice_cmd = None
        self.active_voice_time = float('-inf')
        self.active_eeg_cmd = None
        self.active_eeg_time = float('-inf')
        self.latest_eeg_score = 0.0

        self.latest_telemetry = {
            "vbat": 0.0, "current": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0, "alt": 0.0,
            "rc_roll": 1500, "rc_pitch": 1500, "rc_yaw": 1500, "rc_throttle": 1000
        }
        self.rc_channels = {
            "roll": 1500.0, "pitch": 1500.0, "yaw": 1500.0, "throttle": 1000.0, "arm": 1000
        }
        self.target_rc_channels = {
            "roll": 1500.0, "pitch": 1500.0, "yaw": 1500.0, "throttle": 1000.0
        }

        self.lsl_stream_name = "OpenBCI_Mock"
        self.eeg_channels =[0, 1, 2, 3, 4, 5, 6, 7]
        self.bandpass_order = 4
        self.notch_q = 30.0

        print("[System] Loading Vosk speech recognition model...")
        model_path = "vosk-model-small-en-us-0.15"  # ✏️ TUNE: Update if you download a larger/different language Vosk model
        if not os.path.exists(model_path):
            print(f"[ERROR] Vosk model not found at {model_path}. Please download it.")
            raise SystemExit(1)

        self.vosk_model = Model(model_path)
        grammar = json.dumps([cmd.value.lower() for cmd in Command] + ["take off", "[unk]"])
        self.recognizer = KaldiRecognizer(self.vosk_model, 16000, grammar)

    # =========================================================================
    # CORE: TELEMETRY
    # =========================================================================

    def telemetry_listener_thread(self):
        print(f"[Telemetry] Listening for Betaflight data on port {self.telemetry_port}...")
        print(f"[Telemetry] Logging to: {self.log_filename}")
        last_rx_time = time.time()

        while True:
            try:
                data, _ = self.telemetry_rx_socket.recvfrom(1024)
                last_rx_time = time.time()
                telemetry_data = json.loads(data.decode("utf-8"))
                telemetry_data["system_time"] = time.time()

                t_type = telemetry_data.get("type")
                if t_type == "analog":
                    self.latest_telemetry["vbat"] = telemetry_data.get("vbat", 0.0)
                    self.latest_telemetry["current"] = telemetry_data.get("current", 0.0)
                elif t_type == "attitude":
                    self.latest_telemetry["roll"] = telemetry_data.get("roll", 0.0)
                    self.latest_telemetry["pitch"] = telemetry_data.get("pitch", 0.0)
                    self.latest_telemetry["yaw"] = telemetry_data.get("yaw", 0.0)
                elif t_type == "altitude":
                    self.latest_telemetry["alt"] = telemetry_data.get("alt", 0.0)
                elif t_type == "rc":
                    self.latest_telemetry["rc_roll"] = telemetry_data.get("roll", 1500)
                    self.latest_telemetry["rc_pitch"] = telemetry_data.get("pitch", 1500)
                    self.latest_telemetry["rc_yaw"] = telemetry_data.get("yaw", 1500)
                    self.latest_telemetry["rc_throttle"] = telemetry_data.get("throttle", 1000)

                with open(self.log_filename, "a") as f:
                    f.write(json.dumps(telemetry_data) + "\n")

            except TimeoutError:
                if time.time() - last_rx_time >= 5.0:
                    print("[Telemetry] WARNING: No data received for 5s. Check Betaflight connection.")
            except Exception:
                pass

    # =========================================================================
    # CORE: VOICE PROCESSING
    # =========================================================================

    def _map_speech_to_command(self, text: str) -> Command | None:
        text = text.lower().strip()
        if "take off" in text or "takeoff" in text: return Command.TAKEOFF
        if "land" in text:     return Command.LAND
        if "forward" in text:  return Command.FORWARD
        if "backward" in text: return Command.BACKWARD
        if "left" in text:     return Command.LEFT
        if "right" in text:    return Command.RIGHT
        if "stop" in text:     return Command.STOP
        return None

    def audio_callback(self, indata, _frames, _time_info, _status):
        # 1. 원시 바이트 데이터를 16비트 숫자(정수) 배열로 변환
        audio_data = np.frombuffer(indata, dtype=np.int16)
        
        # 2. 물리적 소리 감지 (Speech Onset)
        peak_volume = np.max(np.abs(audio_data))
        
        if peak_volume > self.audio_threshold and self.speech_onset_time == 0.0:
            self.speech_onset_time = time.time()
            
        # 3. Vosk 음성 인식 처리 
        if self.recognizer.AcceptWaveform(bytes(indata)):
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").strip()        
            
            if text:
                cmd = self._map_speech_to_command(text)
                if cmd:
                    # 💡 첫 번째 레이턴시 측정: 인식 완료 시간
                    self.last_voice_latency = time.time() - self.speech_onset_time
                    
                    print(f"[VOICE] Heard: '{text}' → {cmd.value} (Peak Vol: {peak_volume}, Latency: {self.last_voice_latency:.3f}s)")
                    
                    self.active_voice_cmd = cmd
                    self.active_voice_time = self.speech_onset_time
            
            # 텔레메트리 검증이 끝날 때까지 0으로 초기화하지 않고 보존합니다. (run 루프에서 초기화 처리)

    # =========================================================================
    # CORE: EEG PROCESSING
    # =========================================================================

    def _build_filters(self, sample_rate: float):
        nyq = sample_rate / 2.0
        bandpass_sos = butter(self.bandpass_order,[self.bandpass_low_hz / nyq, self.bandpass_high_hz / nyq], btype="band", output="sos")
        b_notch, a_notch = iirnotch(self.notch_freq_hz / nyq, self.notch_q)
        from scipy.signal import tf2sos
        return bandpass_sos, tf2sos(b_notch, a_notch)

    def _preprocess_eeg(self, eeg_data, bandpass_sos, notch_sos):
        cleaned = detrend(eeg_data, axis=0)
        cleaned = sosfiltfilt(notch_sos, cleaned, axis=0)
        cleaned = sosfiltfilt(bandpass_sos, cleaned, axis=0)
        cleaned = cleaned - cleaned.mean(axis=1, keepdims=True)
        return cleaned

    def _generate_reference_signals(self, length, sample_rate, target_freq):
        t = np.arange(length) / sample_rate
        refs =[]
        for h in range(1, self.num_harmonics + 1):
            refs.append(np.sin(2 * np.pi * h * target_freq * t))
            refs.append(np.cos(2 * np.pi * h * target_freq * t))
        return np.array(refs).T

    def analyze_ssvep_window(self, eeg_data, sample_rate):
        samples = eeg_data.shape[0]
        best_freq, best_score = None, 0.0

        if np.allclose(eeg_data, 0.0, atol=1e-8) or np.var(eeg_data) < 1e-8:
            self.latest_eeg_score = 0.0
            return None, 0.0

        for freq in FREQ_TO_COMMAND:
            y_ref = self._generate_reference_signals(samples, sample_rate, freq)
            cca = CCA(n_components=1)
            cca.fit(eeg_data, y_ref)
            X_c, Y_c = cca.transform(eeg_data, y_ref)

            with np.errstate(divide='ignore', invalid='ignore'):
                score = float(np.corrcoef(X_c[:, 0], Y_c[:, 0])[0, 1])

            if np.isnan(score):
                score = 0.0

            if score > best_score:
                best_score = score
                best_freq = freq

        self.latest_eeg_score = best_score
        if best_score >= self.confidence_threshold:
            return best_freq, best_score
        return None, best_score

    def eeg_polling_thread(self):
        inlet = None
        while inlet is None:
            print(f"[EEG] Looking for LSL stream named '{self.lsl_stream_name}'...")
            streams = resolve_byprop('name', self.lsl_stream_name, timeout=5.0)
            if streams:
                inlet = StreamInlet(streams[0])
            else:
                print("[EEG] Stream not found. Retrying in 5 seconds... (Is server.py running?)")
                time.sleep(5)

        srate = inlet.info().nominal_srate() or 256.0
        window_samples = int(srate * self.window_seconds)
        step_samples = int(srate * self.window_seconds * self.window_step_fraction)
        data_buffer =[]

        bandpass_sos, notch_sos = self._build_filters(srate)

        print(f"[EEG] Connected! Rate: {srate:.0f} Hz | Window: {self.window_seconds}s | 8 Channels")

        while True:
            chunk, _ = inlet.pull_chunk(timeout=0.1, max_samples=window_samples)
            if chunk:
                for sample in chunk:
                    data_buffer.append([sample[i] for i in self.eeg_channels])

            if len(data_buffer) >= window_samples:
                data_buffer = data_buffer[-window_samples:]
                eeg_window = np.array(data_buffer, dtype=np.float64)

                eeg_clean = self._preprocess_eeg(eeg_window, bandpass_sos, notch_sos)
                best_freq, score = self.analyze_ssvep_window(eeg_clean, srate)

                if best_freq is not None:
                    cmd = FREQ_TO_COMMAND[best_freq]
                    print(f"[EEG] Detected: {best_freq:>5.2f} Hz  (Score: {score:.3f})  →  {cmd.value}")
                    self.active_eeg_cmd = cmd
                    self.active_eeg_time = time.time()
                    
                    if self.speech_onset_time == 0.0:
                        self.speech_onset_time = time.time() - self.window_seconds

                    data_buffer =[]
                else:
                    data_buffer = data_buffer[step_samples:]

            time.sleep(0.01)

    # =========================================================================
    # CORE: DRONE COMMAND LOGIC
    # =========================================================================

    def _set_neutral_movement(self):
        self.target_rc_channels["pitch"] = 1500.0
        self.target_rc_channels["roll"] = 1500.0

    def _disarm(self):
        self.rc_channels["throttle"] = 1000.0
        self.target_rc_channels["throttle"] = 1000.0
        self.rc_channels["arm"] = 1000
        self._set_neutral_movement()
        self.rc_channels["pitch"] = 1500.0
        self.rc_channels["roll"] = 1500.0

    def apply_command(self, command: Command):
        vbat = self.latest_telemetry["vbat"]
        alt = self.latest_telemetry.get("alt", 0.0)
        vbat_str = f"[{vbat:.1f}V]" if vbat > 0 else "[No VBat]"
        alt_str = f"[{alt:.2f}m]"

        if command is Command.STOP:
            print(f"\n{vbat_str} {alt_str} [EMERGENCY STOP] Disarming immediately.")
            self._disarm()
            self.is_moving = False
            self.drone_state = DroneState.GROUNDED
            return

        if self.drone_state is DroneState.GROUNDED:
            if command is not Command.TAKEOFF:
                print(f"{vbat_str} {alt_str} [BLOCKED] Grounded. Takeoff first. (Ignored: {command.value})")
                return
            print(f"\n{vbat_str} {alt_str} [TAKEOFF] Arming and spooling up motors.")
            self.rc_channels["arm"] = 2000
            self.target_rc_channels["throttle"] = 1600.0
            self.drone_state = DroneState.AIRBORNE

        elif self.drone_state is DroneState.AIRBORNE:
            if command is Command.TAKEOFF: return
            if command is Command.LAND:
                print(f"\n{vbat_str} {alt_str} [LAND] Disarming and landing.")
                self._disarm()
                self.is_moving = False
                self.drone_state = DroneState.GROUNDED
                return

            print(f"{vbat_str} {alt_str} [MOVE] {command.value}")

            if command is Command.FORWARD:  self.target_rc_channels["pitch"] = 1600.0
            if command is Command.BACKWARD: self.target_rc_channels["pitch"] = 1400.0
            if command is Command.LEFT:     self.target_rc_channels["roll"]  = 1400.0
            if command is Command.RIGHT:    self.target_rc_channels["roll"]  = 1600.0

            self.last_movement_time = time.time()
            self.is_moving = True

    # =========================================================================
    # CORE: MAIN CONTROL LOOP
    # =========================================================================

    def run(self):
        print("=" * 60)
        print(f"  Drone Ground Control — {self.mode.value} MODE")
        print(f"  Target ESP32: {self.esp32_ip}:{self.esp32_port}")
        print("=" * 60)

        threading.Thread(target=self.eeg_polling_thread, daemon=True).start()
        threading.Thread(target=self.telemetry_listener_thread, daemon=True).start()

        print("[State] Drone is GROUNDED and disarmed. Trigger TAKEOFF to begin.\n")

        try:
            with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16", channels=1, callback=self.audio_callback):
                while True:
                    now = time.time()

                    # 1. Expire stale commands
                    if now - self.active_voice_time > self.command_expiry_seconds: self.active_voice_cmd = None
                    if now - self.active_eeg_time > self.command_expiry_seconds:   self.active_eeg_cmd = None

                    final_cmd = None

                    # 2. Logic & Fusion rules
                    if self.active_voice_cmd is Command.STOP or self.active_eeg_cmd is Command.STOP:
                        final_cmd = Command.STOP
                        self.active_voice_cmd = self.active_eeg_cmd = None

                    elif self.mode is ExperimentMode.VOICE_ONLY:
                        if self.active_voice_cmd:
                            final_cmd = self.active_voice_cmd
                            self.active_voice_cmd = None

                    elif self.mode is ExperimentMode.EEG_ONLY:
                        if self.active_eeg_cmd:
                            final_cmd = self.active_eeg_cmd
                            self.active_eeg_cmd = None

                    elif self.mode is ExperimentMode.BOTH:
                        if self.active_voice_cmd and self.active_eeg_cmd:
                            if self.active_voice_cmd is self.active_eeg_cmd:
                                print(f"[FUSION] Agreement on {self.active_voice_cmd.value} → Executing.")
                                final_cmd = self.active_voice_cmd
                            else:
                                print(f"[FUSION] Disagree (Voice: {self.active_voice_cmd.value} vs EEG: {self.active_eeg_cmd.value}) → Ignored.")
                            
                            self.active_voice_cmd = self.active_eeg_cmd = None

                    # 3. Execution & Data Staging
                    if final_cmd:
                        self.apply_command(final_cmd)
                        
                        # 명령 전송과 동시에 대기열(Queue)에 데이터를 올립니다.
                        self.pending_telemetry_cmd = final_cmd
                        
                        # 엑셀 기록을 위한 임시 배열
                        self.pending_csv_data = [
                            datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3],
                            self.mode.value,
                            self.active_voice_cmd.value if self.active_voice_cmd else "NONE",
                            f"{self.latest_eeg_score:.4f}",
                            self.active_eeg_cmd.value if self.active_eeg_cmd else "NONE",
                            final_cmd.value
                        ]

                    # 4. Auto-Stop Movement
                    if self.is_moving and (now - self.last_movement_time > self.action_duration):
                        print("[AUTO-STOP] Returning to neutral hover.")
                        self._set_neutral_movement()
                        self.is_moving = False

                    # 5. Interpolation (Smoothing)
                    for axis in["roll", "pitch", "yaw", "throttle"]:
                        if self.enable_smoothing:
                            diff = self.target_rc_channels[axis] - self.rc_channels[axis]
                            self.rc_channels[axis] += diff * self.smoothing_factor
                        else:
                            self.rc_channels[axis] = self.target_rc_channels[axis]

                    # 6. UDP Transmission to ESP32
                    if self.mode is not ExperimentMode.PHYSICAL_RC:
                        esp32_payload = (
                            f"{int(self.rc_channels['roll'])},"
                            f"{int(self.rc_channels['pitch'])},"
                            f"{int(self.rc_channels['yaw'])},"
                            f"{int(self.rc_channels['throttle'])},"
                            f"{self.rc_channels['arm']}"
                        )
                        self.udp_socket.sendto(esp32_payload.encode("utf-8"), (self.esp32_ip, self.esp32_port))

                    # 7. Test Runner Telemetry
                    runner_payload = {
                        "state": self.drone_state.value,
                        "voice_cmd": self.active_voice_cmd.value if self.active_voice_cmd else None,
                        "eeg_cmd": self.active_eeg_cmd.value if self.active_eeg_cmd else None,
                        "final_cmd": final_cmd.value if final_cmd else None,
                        "is_moving": self.is_moving,
                        "eeg_score": self.latest_eeg_score,
                        "rc_channels": self.rc_channels,
                        "fc_telemetry": self.latest_telemetry
                    }
                    self.test_runner_socket.sendto(json.dumps(runner_payload).encode("utf-8"), (self.test_runner_ip, self.test_runner_port))

                    # 8. 💡 두 번째 레이턴시 측정: 드론 텔레메트리 피드백 확인 (End-to-End Latency)
                    if self.pending_telemetry_cmd and self.speech_onset_time > 0.0:
                        pitch_ok = abs(self.latest_telemetry["rc_pitch"] - self.target_rc_channels["pitch"]) < 50
                        roll_ok = abs(self.latest_telemetry["rc_roll"] - self.target_rc_channels["roll"]) < 50
                        thr_ok = abs(self.latest_telemetry["rc_throttle"] - self.target_rc_channels["throttle"]) < 50
                        
                        # 파이썬이 요구한 값으로 드론의 RC 값이 도달했다면 (FC가 명령을 완벽히 수신했다면)
                        if pitch_ok and roll_ok and thr_ok:
                            drone_latency = time.time() - self.speech_onset_time
                            
                            print("-" * 50)
                            print(f"📊 [LATENCY REPORT] Target Command: {self.pending_telemetry_cmd.value}")
                            print(f"   - Voice Recog Time: {self.last_voice_latency:.3f} s")
                            print(f"   - Drone Recog Time: {drone_latency:.3f} s")
                            print("-" * 50)
                            
                            # 최종 레이턴시 수치 2개를 포함하여 CSV에 한 줄 작성
                            if self.pending_csv_data:
                                with open(self.csv_filename, mode='a', newline='') as file:
                                    writer = csv.writer(file)
                                    row = self.pending_csv_data + [f"{self.last_voice_latency:.3f}", f"{drone_latency:.3f}"]
                                    writer.writerow(row)
                                
                            # 기록 완료 후 대기열 및 타이머 초기화 (다음 명령 대기)
                            self.pending_telemetry_cmd = None
                            self.pending_csv_data = None
                            self.speech_onset_time = 0.0

                    time.sleep(0.02) # 50Hz Loop

        except KeyboardInterrupt:
            print("\n[System] Ctrl+C received — shutting down.")
            self._disarm()
            payload = (
                f"{int(self.rc_channels['roll'])},"
                f"{int(self.rc_channels['pitch'])},"
                f"{int(self.rc_channels['yaw'])},"
                f"{int(self.rc_channels['throttle'])},"
                f"{self.rc_channels['arm']}"
            )
            self.udp_socket.sendto(payload.encode("utf-8"), (self.esp32_ip, self.esp32_port))


if __name__ == "__main__":
    controller = DroneController()
    controller.run()
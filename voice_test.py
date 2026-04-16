import json
import time
from vosk import Model, KaldiRecognizer
import sounddevice as sd

model = Model("vosk-model-small-en-us-0.15")

list_of_commands = '["take off", "land", "forward", "backward", "[unk]", "right", "left", "stop"]'
rec = KaldiRecognizer(model, 16000, list_of_commands)

last_command = None
last_sent_time = 0
COMMAND_COOLDOWN = 1  # ?? ?? ?? ?? ??

def map_speech_to_command(text: str):
    text = text.lower().strip()

    if "take off" in text or "takeoff" in text:
        return "TAKEOFF"
    elif "land" in text:
        return "LAND"
    elif "forward" in text:
        return "FORWARD"
    elif "backward" in text or "back" in text:
        return "BACKWARD"
    elif "left" in text:
        return "LEFT"
    elif "right" in text:
        return "RIGHT"
    elif "stop" in text or "hover" in text:
        return "STOP"
    else:
        return None

def send_signal(command: str):
    global last_command, last_sent_time

    now = time.time()

    if command == last_command and (now - last_sent_time) < COMMAND_COOLDOWN:
        return

    print(f"[SIGNAL SENT] CMD:{command}")
    last_command = command
    last_sent_time = now

def callback(indata, frames, time_info, status):
    if status:
        print("[AUDIO STATUS]", status)

    if rec.AcceptWaveform(bytes(indata)):
        result = json.loads(rec.Result())
        text = result.get("text", "").strip()

        if text:
            print("[FINAL]", text)
            command = map_speech_to_command(text)

            if command:
                send_signal(command)
            else:
                print("[INFO] No valid command detected.")
    else:
        partial = json.loads(rec.PartialResult())
        partial_text = partial.get("partial", "").strip()

        if partial_text:
            print("[PARTIAL]", partial_text)

print("Listening...")
print("Press Ctrl+C to stop.")

try:
    with sd.RawInputStream(
        samplerate=16000,
        blocksize=8000,
        dtype="int16",
        channels=1,
        callback=callback
    ):
        while True:
            time.sleep(0.1)

except KeyboardInterrupt:
    print("\nStopped by user.")
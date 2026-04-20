import pyaudio
import numpy as np
import time

CHANNELS = 1
RATE = 48000 # 48kHz nativo para MAX98357
DURATION = 3 # Segundos
FREQUENCY = 440.0 # Hz (Nota La)

p = pyaudio.PyAudio()

print("Generando pitido Float32 a 48000Hz nativos...")

# Usamos paFloat32 directo sin depender de asoundrc plug
samples = (np.sin(2*np.pi*np.arange(RATE*DURATION)*FREQUENCY/RATE)).astype(np.float32)
audio_bytes = samples.tobytes()

# Buscamos el dispositivo voiceHAT
device_idx = None
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if "voiceHAT" in info.get("name", ""):
        device_idx = i
        break

print(f"Device index: {device_idx}")

stream = p.open(format=pyaudio.paFloat32, channels=CHANNELS, rate=RATE, output=True, output_device_index=device_idx)
stream.write(audio_bytes)
stream.stop_stream()
stream.close()

p.terminate()
print("Fin de la prueba a 48kHz.")

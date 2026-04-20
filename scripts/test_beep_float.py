import pyaudio
import numpy as np
import time

CHANNELS = 1
RATE = 16000
DURATION = 3 # Segundos
FREQUENCY = 440.0 # Hz (Nota La)

p = pyaudio.PyAudio()

print("Generando pitido S32_LE (16kHz escalado a Float32)...")

# 1. Generamos como Int16 igual que ElevenLabs
samples_int16 = (np.sin(2*np.pi*np.arange(RATE*DURATION)*FREQUENCY/RATE) * 32767).astype(np.int16)
audio_bytes = samples_int16.tobytes()

# 2. Re-escalamos a Float32 como hacemos ahora en audio_hub.py
audio_float32 = (np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0).tobytes()

# 3. Empujamos al stream en formato paFloat32
stream = p.open(format=pyaudio.paFloat32, channels=CHANNELS, rate=RATE, output=True)
stream.write(audio_float32)
stream.stop_stream()
stream.close()

p.terminate()
print("Fin de la prueba.")

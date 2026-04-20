import pyaudio
import numpy as np

CHANNELS = 1
RATE = 16000
DURATION = 3 # Segundos
FREQUENCY = 440.0 # Hz (Nota La)

p = pyaudio.PyAudio()

print("Generando pitido S16_LE (16kHz)...")
samples_int16 = (np.sin(2*np.pi*np.arange(RATE*DURATION)*FREQUENCY/RATE) * 32767).astype(np.int16)
stream_int16 = p.open(format=pyaudio.paInt16, channels=CHANNELS, rate=RATE, output=True)
stream_int16.write(samples_int16.tobytes())
stream_int16.stop_stream()
stream_int16.close()

p.terminate()
print("Fin de la prueba.")

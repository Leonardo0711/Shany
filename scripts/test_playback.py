import pyaudio
import numpy as np

# Configuración
CHANNELS = 1
RATE = 44100
DURATION = 3 # segundos
FREQUENCY = 440.0 # Hz (Nota La)

p = pyaudio.PyAudio()

# Generar un tono simple
samples = (np.sin(2*np.pi*np.arange(RATE*DURATION)*FREQUENCY/RATE)).astype(np.float32)

print("Iniciando prueba de reproducción (MAX98357)...")
stream = p.open(format=pyaudio.paFloat32,
                channels=CHANNELS,
                rate=RATE,
                output=True)

stream.write(samples.tobytes())

print("Reproducción finalizada.")
stream.stop_stream()
stream.close()
p.terminate()

import pyaudio
import numpy as np
import time

CHANNELS = 1
DURATION = 2 # Segundos por pitido
FREQUENCIES = [440.0, 660.0, 880.0] # Diferentes tonos para distinguirlos

p = pyaudio.PyAudio()

rates_to_test = [16000, 32000, 48000]

print("Iniciando prueba de 3 barridos de Frecuencia de Sonido (Float32)")

for idx, rate in enumerate(rates_to_test):
    freq = FREQUENCIES[idx]
    print(f"\n--- Probando a {rate}Hz ---")
    try:
        # Generamos la onda seno
        samples = (np.sin(2*np.pi*np.arange(rate*DURATION)*freq/rate)).astype(np.float32)
        audio_bytes = samples.tobytes()

        # Abrimos el stream (confiando en que ALSA plug se encarga de re-muestrear si es necesario)
        stream = p.open(format=pyaudio.paFloat32, channels=CHANNELS, rate=rate, output=True)
        stream.write(audio_bytes)
        stream.stop_stream()
        stream.close()
        print(f"Éxito enviando pitido de {rate}Hz al driver.")
    except Exception as e:
        print(f"Error al enviar pitido de {rate}Hz: {e}")
    
    time.sleep(1) # Pausa entre pitidos

p.terminate()
print("\nPrueba de 3 fases completada.")

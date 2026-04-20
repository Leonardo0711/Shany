import pyaudio
import wave

# Configuración
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
CHUNK = 1024
RECORD_SECONDS = 5
WAVE_OUTPUT_FILENAME = "test_recording.wav"

audio = pyaudio.PyAudio()

# Listar dispositivos para depuración
info = audio.get_host_api_info_by_index(0)
numdevices = info.get('deviceCount')
print(f"Buscando dispositivos de entrada (Micrófono INMP441)...")
for i in range(0, numdevices):
    if (audio.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
        print(f"ID {i}: {audio.get_device_info_by_host_api_device_index(0, i).get('name')}")

# Abrir stream
stream = audio.open(format=FORMAT, channels=CHANNELS,
                    rate=RATE, input=True,
                    frames_per_buffer=CHUNK)

print("* Grabando por 5 segundos...")

frames = []
for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
    data = stream.read(CHUNK)
    frames.append(data)

print("* Grabación finalizada.")

stream.stop_stream()
stream.close()
audio.terminate()

# Guardar en archivo
wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
wf.setnchannels(CHANNELS)
wf.setsampwidth(audio.get_sample_size(FORMAT))
wf.setframerate(RATE)
wf.writeframes(b''.join(frames))
wf.close()

print(f"Archivo guardado como: {WAVE_OUTPUT_FILENAME}")

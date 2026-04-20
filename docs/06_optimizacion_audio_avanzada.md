# Paso 6: Optimización de Sonido y Filtrado DSP

Este documento explica las soluciones acústicas aplicadas para superar la limitación del hardware I2S y mejorar la calidad de voz del bot en entornos reales.

## 1. El Puente ALSA (`.asoundrc`)

El hardware original solo procesa un Sample Rate de `48000Hz` a `32-bit`. Como la inteligencia artificial (ElevenLabs y el Hotword Engine) funcionan mejor u obligatoriamente a `16000Hz` mono, la conversión en Python es ineficiente en una Raspberry Pi Zero 2W. 

Para que la Raspberry maneje la traducción en hardware (kernel-level), creamos un "enchufe" o puente en la configuración de la propia máquina. 

Específicamente, en `/home/ietsi/.asoundrc` (este archivo debe crearse en la Raspberry si se formatea), aplicamos esta definición mínima para declarar `plughw:0,0` como el puente nativo:

```text
pcm.!default {
    type asym
    playback.pcm "plughw:0,0"
    capture.pcm  "plughw:0,0"
}
```

*Nota:* PyAudio está configurado para buscar el dispositivo ALSA `plughw` en lugar de `hw`. Es este "plug" el que resamplea silenciosamente el audio de 16k a 48k y viceversa.

## 2. DSP (Procesamiento Digital de Señales)

Debido a la distancia del micrófono (INMP441) y la potencia de salida del amplificador (MAX98357), el AudioHub implementa un procesamiento digital vectorizado utilizando la velocidad de Numpy. Estos filtros han sido centralizados en `config.py` para un fácil mantenimiento.

### 2.1 Cadena de entrada (Micrófono)
Se aplican dos filtros sobre el audio entrante (frames de 3200 muestras):
1.  **Cancelación de DC Offset:** El chip INMP441 tiene cierta variación de voltaje que genera ruido eléctrico constante ("rumble"). Eliminamos este offset sustrayendo la media del frame (`raw -= np.mean(raw)`).
2.  **Ganancia 5x (`mic_gain`):** Esto extiende artificialmente el radio de captación de voz a varios metros. Luego hacemos un corte limpio (`np.clip()`) a `int16` para evitar estática si alguien grita muy cerca.

### 2.2 Cadena de salida (Altavoz)
En el resampleo de 16kHz a 48kHz, el audio a menudo genera picos o asperezas sintéticas. Para solucionarlo sin perder volumen:
1.  **Compresión Suave (Soft-Knee Compress):** En lugar de recortar bruscamente las ondas que cruzan el umbral de dolor auditivo o saturación (`output_comp_threshold = 0.6`), se reducen exponencialmente. El sonido se mantiene alto pero seguro.
2.  **Volumen Maestro (`output_gain`):** Elevado artificialmente a 2.5x para garantizar que la voz domine frente al ruido de la habitación.

---
*Si deseas cambiar cuán lejos Shany escucha, o cuán fuerte habla, no modifiques algoritmos DSP. Solo edita los valores en `shany_app_pi/config.py`.*

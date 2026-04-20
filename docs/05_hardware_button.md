# Paso 5: Implementación de Botón Físico (GPIO) y Parche de Audio

## 1. Parche de Audio (ALSA `plughw`)
Debido a las estrictas limitaciones paramétricas del hardware Cero de I2S (MAX98357/INMP441) configurado bajo el overlay de Google VoiceHAT, no es posible abrir el stream nativo de audio a `16kHz / 16-bit / Mono`.

- **Problema:** PyAudio intentaba forzar los 16kHz sobre un hardware que solo procesa 48kHz nativos, resultando en `OSError: Invalid sample rate`.
- **Solución Aplicada:** En lugar de saturar la CPU de la Raspberry Pi Zero 2W con una conversión matemática en Python puro, utilizamos el dispositivo virtual `plughw:0,0` nativo de ALSA. Este driver actúa como una capa de abstracción que hace resampleo automático a nivel del kernel con un costo de CPU casi nulo antes de entregárselo a PyAudio.

## 2. Botón Físico Multifunción (Mecanismo de Respaldo)
Para evitar depender estrictamente del motor de Wake Word ("Hola Shany") o de la detección de interrupciones de voz ("Shany"), se añadió un control táctil usando `gpiozero`.

### 2.1. Conexión Eléctrica (Wiring)
Es importante realizar la conexión correctamente ya que un cortocircuito con un pin de 5V podría dañar el SoC de la Raspberry Pi.

| Elemento | Pin Físico RPi | Descripción GPIO |
| :--- | :--- | :--- |
| **Pata 1 (Botón)** | Pin 16 | GPIO 23 |
| **Pata 2 (Botón)** | Pin 14 | Ground (GND) |

*Nota Eléctrica:* Usamos la resistencia "Pull-Up" interna administrada automáticamente por `gpiozero.Button`. Por defecto leerá `HIGH` y al presionar hará contacto con tierra, marcando `LOW`. Sin resistencias físicas requeridas.

### 2.2. Lógica de Activación y Comportamiento del Software
El algoritmo se escribió de forma asíncrona mediante el uso de timers en Python para no bloquear el bucle (loop) principal de ejecución en `app.py`.

*   **Pulsación Simple (Single Click < 0.4s):**
    *   *Comportamiento:* Equivalente a que la IA detecte "Hola Shany".
    *   *Acción:* Despierta a Shany y abre directamente la sesión con ElevenLabs.
*   **Paso Largo (Hold / Long Press > 1.0s):**
    *   *Comportamiento:* Equivalente a la palabra "Shany".
    *   *Acción:* Apaga el altavoz temporalmente, corta el flujo de habla actual del agente e inmediatamente captura el micrófono de forma forzada para oír tu comando.
*   **Pulsación Doble (Double Click):**
    *   *Comportamiento:* Protocolo de emergencia o término manual del flujo.
    *   *Acción:* Cierra de golpe la sesión de ElevenLabs de regreso a estado Standby sin esperar inactividad.

---
*Este registro corresponde a la etapa de madurez técnica del dispositivo. Pendiente de ejecución vía los tests indicados en el plan de implementación.*

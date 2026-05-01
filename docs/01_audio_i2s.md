# Paso 1: Configuración de Audio I2S (MAX98357 + INMP441)

Este documento detalla los pasos para habilitar el hardware de audio I2S en la Raspberry Pi Zero 2W.

## 1. Conexión de Hardware
Asegúrate de que los módulos estén conectados a los siguientes pines GPIO:

| Módulo   | Pin del módulo | Raspberry Pi | Pin Físico |
| -------- | -------------- | ------------ | ---------- |
| **INMP441** | VDD            | 3.3V         | 1 o 17     |
| **INMP441** | SCK            | GPIO18       | 12         |
| **INMP441** | WS             | GPIO19       | 35         |
| **INMP441** | SD             | GPIO20       | 38         |
| **INMP441** | L/R            | GND          |            |
| **MAX98357**| VIN            | 5V           | 2 o 4      |
| **MAX98357**| BCLK           | GPIO18       | 12         |
| **MAX98357**| LRC            | GPIO19       | 35         |
| **MAX98357**| DIN            | GPIO21       | 40         |
| **MAX98357**| SD             | 5V           | 2 o 4      |

## 2. Habilitar Interfaz I2S en el Kernel
Debemos editar el archivo `/boot/firmware/config.txt` para activar el bus I2S y cargar el driver de sonido.

### Comandos ejecutados:
Se agregaron/modificaron las siguientes líneas en `/boot/firmware/config.txt`:
```bash
# Habilitar I2S
dtparam=i2s=on

# Cargar el overlay para el DAC (Amp) y el ADC (Mic)
dtoverlay=googlevoicehat-soundcard
```

## 3. Instalación de Dependencias de Sistema
Para que las librerías de Python (como `pyaudio`) puedan interactuar con el sonido, instalamos las herramientas de ALSA y PortAudio.

```bash
sudo apt update
sudo apt install -y portaudio19-dev libasound2-dev alsa-utils
```

## 4. Reinicio
Los cambios en `config.txt` solo surten efecto tras un reinicio:
```bash
sudo reboot
```

## 5. Verificación (Tras reiniciar)
Para confirmar que el hardware ha sido detectado, ejecutamos:

- **Reproducción (DAC):** `aplay -l`
- **Grabación (ADC):** `arecord -l`

### Resultado obtenido:
```text
**** List of PLAYBACK Hardware Devices ****
card 0: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar], device 0: Google voiceHAT SoundCard HiFi voicehat-hifi-0 [Google voiceHAT SoundCard HiFi voicehat-hifi-0]

**** List of CAPTURE Hardware Devices ****
card 0: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar], device 0: Google voiceHAT SoundCard HiFi voicehat-hifi-0 [Google voiceHAT SoundCard HiFi voicehat-hifi-0]
```
Si ves la tarjeta `sndrpigooglevoi`, ¡el hardware está listo!

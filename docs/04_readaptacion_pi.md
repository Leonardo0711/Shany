# Paso 4: Readaptación y Despliegue en Raspberry Pi Zero 2W

Este documento detalla el proceso técnico completo de migración y optimización de Shany para ejecutarse en el hardware restrictivo de la Pi Zero 2W.

## 1. Preparación del Sistema (Hardware Limits)
Dado que la Pi Zero 2W solo cuenta con 512MB de RAM, el sistema se agotaba rápidamente durante la instalación de dependencias de IA.

### 1.1. Ampliación de Memoria Virtual (Swap)
Para evitar que el kernel matara procesos (`OOM Killer`), incrementamos el swap a **1GB**:
1. **Creación del archivo:** `sudo dd if=/dev/zero of=/swapfile bs=1M count=1024`
2. **Permisos:** `sudo chmod 600 /swapfile`
3. **Formateo:** `sudo mkswap /swapfile`
4. **Activación:** `sudo swapon /swapfile`
*Esto permitió que `pip` compilara paquetes pesados sin colapsar el sistema.*

## 2. Entorno de Ejecución
Creamos un entorno virtual aislado para no interferir con las librerías del sistema y cumplir con las políticas de "Externally Managed Environments" de Debian Bookworm.
- **Ruta:** `/home/ietsi/shany_env`
- **Comando:** `python3 -m venv /home/ietsi/shany_env`

## 3. Instalación de Dependencias (El "Cuello de Botella")
Este paso fue el más crítico y lento. Se instalaron componentes que requieren alta capacidad de procesamiento para su configuración inicial:

| Paquete | Importancia | Detalle |
| :--- | :--- | :--- |
| **EfficientWord-Net** | Motor de Wake Word | Paquete de ~101MB que maneja el reconocimiento local de "Hola Shany". |
| **onnxruntime** | Motor de Inferencia | Runtime optimizado para ejecutar modelos de IA en arquitectura ARM. |
| **pyaudio** | Interfaz de Audio | Requiere `portaudio19-dev` en el sistema para comunicarse con ALSA. |
| **elevenlabs** | Cliente API | Maneja la comunicación con el Agente Conversacional. |
| **numpy / sympy** | Matemáticas | Librerías base para el procesamiento de señales de audio. |

## 4. Adaptación de Código (Refactorización)
No fue una simple copia; se realizaron cambios estructurales para la Pi:
- **Renombrado del Paquete:** Se migró de `shany_app` a `shany_app_pi` para permitir coexistencia y pruebas aisladas.
- **Corrección de Imports:** Se actualizaron más de 10 declaraciones de importación en archivos como `app.py`, `audio_hub.py` y `conversation_manager.py` para apuntar al nuevo namespace.
- **Estrategia de Despliegue:** Se utilizó `pscp` (PuTTY Secure Copy) para transferir el código adaptado y los modelos de referencia (`.json`) desde el entorno de desarrollo Windows hacia `/home/ietsi/`.

## 5. Pruebas de Integración y Bloqueo de Hardware
Tras finalizar el despliegue, intentamos la primera ejecución mediante `run_shany.sh`.
- **Resultado:** Fallo con `OSError: [Errno -9997] Invalid sample rate`.
- **Causa Técnica:** El hardware I2S (MAX98357/INMP441) configurado mediante el overlay `googlevoicehat` es extremadamente rígido. Solo permite apertura de streams a **48000Hz / 32-bit / Estéreo**.
- **Impacto:** Shany está configurada para **16000Hz / 16-bit / Mono**.

## 6. Estado Actual y Soluciones Implementadas
Hemos completado con éxito toda la base de software y dependencias. El sistema es totalmente estable y solvente para producción gracias al swap de 1GB y las optimizaciones implementadas.

- **Puente ALSA (`plughw`):** Se implementó exitosamente el puente virtual de ALSA para la conversión automática en hardware de 16kHz a 48kHz sin costo de CPU.
- **Botón Físico:** Se integró hardware para rescate e interrupción manual de conversaciones.
- **Audio DSP (Procesamiento Digital):** Se calibró un pipeline completo de audio. El micrófono ahora cancela vibraciones ("dc offset") e incrementa su rango 5x. El parlante incluye un compresor de señal (soft-knee) para eliminar los zumbidos sintéticos manteniendo el volumen alto en 2.5x.

*(Los detalles avanzados del botón y la acústica están desglosados en los documentos 05 y 06 respectivamente).*

---
*Documentación generada para registro técnico del proyecto Shany.*

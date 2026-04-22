# Paso 8: Conexión Serial con ESP32-S3 (Expresiones Faciales)

Este documento detalla la configuración de hardware y software para que Shany envíe sus emociones en tiempo real a una pantalla TFT controlada por un ESP32-S3.

## 1. Cableado Físico (Pinout)

La comunicación se realiza mediante UART (Serial). Es **obligatorio** que el cableado sea cruzado y que compartan la misma tierra.

| Dispositivo | Pin | Función | Destino | Pin Destino |
| :--- | :--- | :--- | :--- | :--- |
| **Raspberry Pi** | Pin 8 | TX (Salida) | **ESP32-S3** | RX (Entrada) |
| **Raspberry Pi** | Pin 10 | RX (Entrada) | **ESP32-S3** | TX (Salida) |
| **Raspberry Pi** | Pin 6 | Ground (GND) | **ESP32-S3** | Ground (GND) |

> [!WARNING]
> Ambos dispositivos trabajan a **3.3V**. Nunca conectes los 5V de la Raspberry a los pines de datos del ESP32 o podrías dañar el controlador.

## 2. Configuración del Sistema (Realizada)

Para que el puerto `/dev/serial0` sea útil para Shany, hemos realizado dos cambios críticos en la Raspberry:
1.  **Liberar UART**: Se eliminó la consola de Linux del puerto serial editando `/boot/firmware/cmdline.txt`.
2.  **Librerías**: Se instaló `pyserial` en el entorno virtual `shany_env`.

## 3. Protocolo de Comunicación (JSON)

Shany envía una línea de texto JSON terminada en `\n` por cada evento visual. Existen 4 tipos de mensajes que tu ESP32 debe procesar:

### A. Emoción Base (`type: emotion`)
Define la cara global (ojos/expresión).
```json
{"type": "emotion", "seq": 5, "emotion": "alegria_suave", "intensity": 0.8, "duration_ms": 3000, "blink": true, "sent_ms": 450123}
```

### B. Estado de Habla (`type: speech_state`)
Indica el inicio y fin exacto de la voz del agente.
```json
{"type": "speech_state", "seq": 6, "speaking": true, "sent_ms": 450150}
```
*   `speaking: true` -> Shany empezó a sonar.
*   `speaking: false` -> Shany terminó de decir su frase.

### C. Lip Sync / Nivel de Boca (`type: speech`)
Se envía varias veces por segundo (~12Hz) mientras `speaking` es `true`.
```json
{"type": "speech", "seq": 7, "mouth": 0.452, "sent_ms": 450180}
```
*   **mouth**: Valor entre `0.0` (totalmente cerrada) y `1.0` (totalmente abierta).

### D. Estado de Interfaz (`type: ui_state`)
Indica cambios en el flujo de la aplicación.
```json
{"type": "ui_state", "seq": 8, "state": "listening", "sent_ms": 450250}
```
*   Se envía automáticamente al terminar de hablar para que los ojos cambien a modo "escucha".

- **seq**: Contador secuencial para detectar pérdida de paquetes.
- **sent_ms**: Tiempo interno de la Pi (monotónico) para medir latencia.

## 4. Código de Prueba para ESP32 (Arduino/PlatformIO)

Utiliza este código mínimo en tu ESP32 para validar que los datos llegan correctamente antes de programar los ojos.

```cpp
#include <Arduino.h>

// Ajusta estos pines según tu placa ESP32-S3
#define RX_PIN 16
#define TX_PIN 17

HardwareSerial ShanyUart(1); // Usamos UART1

void setup() {
  Serial.begin(115200);
  ShanyUart.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);
  Serial.println("ESP32: Esperando datos de Shany...");
}

void loop() {
  if (ShanyUart.available()) {
    String line = ShanyUart.readStringUntil('\n');
    line.trim();
    
    if (line.length() > 0) {
      Serial.print("Recibido: ");
      Serial.println(line);
      // Aquí podrías usar una librería como ArduinoJson para procesar 'line'
    }
  }
}
```

---
*Documentación para la Fase 2 del sistema de expresiones de Shany.*

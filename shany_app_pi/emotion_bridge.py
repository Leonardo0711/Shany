import json
import logging
import threading
import time
from typing import Dict, Any, Optional

try:
    import serial
except ImportError:
    serial = None

log = logging.getLogger(__name__)

class EmotionBridge:
    """
    Gestiona la comunicación de emociones desde ElevenLabs hacia 
    la salida (terminal y hardware ESP32 vía UART).
    """

    def __init__(self, port: str = "/dev/serial0", baudrate: int = 115200) -> None:
        self._start_time = time.time()
        self._seq = 0
        self._ser: Optional[serial.Serial] = None
        self._last_mouth: float = 0.0  # Para filtrado delta
        self._lock = threading.Lock()

        if serial is None:
            log.warning("Librería 'pyserial' no encontrada. Modo UART desactivado.")
            return

        try:
            # Abrimos el puerto con un timeout corto para no bloquear el loop
            self._ser = serial.Serial(
                port=port, 
                baudrate=baudrate, 
                timeout=0.1, 
                write_timeout=0.1
            )
            log.info("EmotionBridge UART listo en %s @ %d", port, baudrate)
        except Exception as e:
            self._ser = None
            log.warning("EmotionBridge no pudo abrir UART (%s). Solo terminal activa.", e)

    def set_emotion(self, parameters: Dict[str, Any]) -> str:
        """
        Callback ejecutado cuando la IA llama a la herramienta 'setEmotion'.
        Envía los datos tanto al terminal como al puerto Serial.
        """
        self._seq += 1
        
        payload = {
            "type": "emotion",
            "seq": self._seq,
            "emotion": parameters.get("emotion", "neutral"),
            "intensity": float(parameters.get("intensity", 0.5)),
            "duration_ms": int(parameters.get("duration_ms", 2000)),
            "blink": bool(parameters.get("blink", True)),
            "sent_ms": int(time.monotonic() * 1000)
        }

        self._send_payload(payload)
        return f"Emotion set to {payload['emotion']} successfully."

    def send_speech_state(self, speaking: bool) -> None:
        """Indica si el bot ha empezado o terminado de hablar."""
        self._seq += 1
        if not speaking:
            self._last_mouth = 0.0  # Reset delta al terminar
        payload = {
            "type": "speech_state",
            "seq": self._seq,
            "speaking": speaking,
            "sent_ms": int(time.monotonic() * 1000)
        }
        self._send_payload(payload)

    def send_speech_level(self, mouth: float) -> None:
        """
        Envía el nivel de apertura de boca (0.0 a 1.0).
        Usa filtrado delta: solo envía si el valor cambió lo suficiente.
        """
        mouth = round(float(mouth), 2)

        # Filtrado delta: no enviar si el cambio es insignificante
        # Esto evita saturar el UART con valores casi idénticos
        if abs(mouth - self._last_mouth) < 0.02:
            return

        self._last_mouth = mouth
        self._seq += 1

        # Formato compacto para speech: menor latencia en UART
        payload = {
            "type": "speech",
            "seq": self._seq,
            "mouth": mouth,
            "sent_ms": int(time.monotonic() * 1000)
        }
        self._send_payload(payload, is_speech=True)

    def send_ui_state(self, state: str) -> None:
        """Cambia el estado visual de la interfaz (ej: listening, thinking)."""
        self._seq += 1
        payload = {
            "type": "ui_state",
            "seq": self._seq,
            "state": state,
            "sent_ms": int(time.monotonic() * 1000)
        }
        self._send_payload(payload)

    def _send_payload(self, payload: Dict[str, Any], is_speech: bool = False) -> None:
        """Salida interna a Terminal y UART (Thread-Safe)."""
        line = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        
        # Imprimir en terminal: estados siempre, speech solo cada 8 paquetes
        if not is_speech or self._seq % 8 == 0:
            print(f"[visual] {line}", flush=True)

        if self._ser is not None:
            with self._lock:
                try:
                    self._ser.write((line + "\n").encode("utf-8"))
                    # Solo flush para paquetes de estado (prioritarios)
                    # Speech se manda en ráfaga sin flush individual para menor latencia
                    if not is_speech:
                        self._ser.flush()
                except Exception:
                    log.exception("Fallo crítico enviando datos por UART")

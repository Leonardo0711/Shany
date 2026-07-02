"""
hotword_engine.py — Detección de hotwords (wake + interrupt).

Encapsula los detectores de eff_word_net y el CustomAudioStream,
exponiendo una API limpia para el orquestador.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional

from eff_word_net.audio_processing import Resnet50_Arc_loss
from eff_word_net.engine import HotwordDetector
from eff_word_net.streams import CustomAudioStream

if TYPE_CHECKING:
    import numpy as np
    from shany_app_pi.audio_hub import AudioHub
    from shany_app_pi.config import ShanyConfig

log = logging.getLogger(__name__)


class HotwordEngine:
    """
    Motor de detección de hotwords.

    - ``check_wake(frame)``      → confidence o None
    - ``check_interrupt(frame)`` → confidence o None
    """

    def __init__(self, config: ShanyConfig, hub: AudioHub) -> None:
        self._cfg = config
        self._last_wake_candidate_log = 0.0

        # Modelo base compartido por ambos detectores
        self._model = Resnet50_Arc_loss()

        self._wake_detector = HotwordDetector(
            hotword="hola_shany",
            model=self._model,
            reference_file=str(config.ref_hola),
            threshold=config.wake_threshold,
            relaxation_time=config.wake_relaxation,
        )

        self._interrupt_detector = HotwordDetector(
            hotword="shany",
            model=self._model,
            reference_file=str(config.ref_shany),
            threshold=config.interrupt_threshold,
            relaxation_time=config.interrupt_relaxation,
        )

        # Stream que alimenta frames desde el AudioHub
        self._stream = CustomAudioStream(
            open_stream=lambda: None,
            close_stream=lambda: None,
            get_next_frame=hub.hotword_next_frame,
            window_length_secs=config.window_length_secs,
            sliding_window_secs=config.sliding_window_secs,
        )
        log.info("HotwordEngine inicializado")

    # ── API pública ──────────────────────────────────────────────

    def start(self) -> None:
        """Arranca el stream del motor de hotword."""
        self._stream.start_stream()
        log.info("HotwordEngine listo")

    def get_frame(self) -> np.ndarray:
        """Bloquea hasta obtener el siguiente frame de audio."""
        return self._stream.getFrame()

    def check_wake(self, frame: np.ndarray) -> Optional[float]:
        """
        Evalúa si el frame contiene la wake-word "Hola Shany".

        Returns:
            Confidence (float) si detectó, o None si no.
        """
        result = self._wake_detector.scoreFrame(frame)
        if result and result.get("match"):
            return float(result["confidence"])
        if result:
            confidence = float(result.get("confidence", 0.0))
            now = time.monotonic()
            if confidence >= 0.45 and (now - self._last_wake_candidate_log) >= 1.0:
                self._last_wake_candidate_log = now
                log.info(
                    "Hotword wake candidato conf=%.3f threshold=%.2f",
                    confidence,
                    self._cfg.wake_threshold,
                )
        return None

    def check_interrupt(self, frame: np.ndarray) -> Optional[float]:
        """
        Evalúa si el frame contiene la interrupt-word "Shany".

        Returns:
            Confidence (float) si detectó, o None si no.
        """
        result = self._interrupt_detector.scoreFrame(frame)
        if result and result.get("match"):
            return float(result["confidence"])
        return None

    def shutdown(self) -> None:
        """Libera recursos del stream."""
        try:
            self._stream.close_stream()
        except Exception:
            pass
        log.info("HotwordEngine apagado")

"""Orquestador principal: OpenAI Realtime + ElevenLabs TTS."""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Optional

from shany_app_pi.audio_hub import AudioHub
from shany_app_pi.config import ShanyConfig
from shany_app_pi.elevenlabs_tts_streamer import ElevenLabsTTSStreamer
from shany_app_pi.emotion_bridge import EmotionBridge
from shany_app_pi.hardware_button import SmartButton
from shany_app_pi.hotword_engine import HotwordEngine
from shany_app_pi.openai_realtime_manager import OpenAIRealtimeManager
from shany_app_pi.shany_prompt import SHANY_INITIAL_GREETING

log = logging.getLogger(__name__)


class _DeltaTextChunker:
    """Agrupa deltas de texto para TTS sin esperar toda la respuesta."""

    def __init__(self, speak_fn, flush_chars: int) -> None:
        self._speak = speak_fn
        self._flush_chars = flush_chars
        self._buf = ""
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._buf = ""

    def feed(self, delta: str) -> None:
        with self._lock:
            self._buf += delta
            while True:
                idx = self._find_sentence_boundary(self._buf)
                if idx < 0 and len(self._buf) < self._flush_chars:
                    return
                if idx < 0:
                    idx = len(self._buf)
                text = self._buf[: idx + 1].strip()
                self._buf = self._buf[idx + 1 :].lstrip()
                if text:
                    self._speak(text)

    def flush(self) -> None:
        with self._lock:
            text = self._buf.strip()
            self._buf = ""
        if text:
            self._speak(text)

    @staticmethod
    def _find_sentence_boundary(text: str) -> int:
        best = -1
        for mark in ".?!\n":
            idx = text.find(mark)
            if idx >= 0 and (best < 0 or idx < best):
                best = idx
        return best


class ShanyRealtimeApp:
    """Aplicacion aislada del motor ElevenLabs Agent anterior."""

    def __init__(self, config: Optional[ShanyConfig] = None) -> None:
        self._cfg = config or ShanyConfig()
        self._cfg.validate_realtime()

        self._emotion = EmotionBridge()
        self._hub = AudioHub(self._cfg, visual_bridge=self._emotion)
        self._hotword = HotwordEngine(self._cfg, self._hub)
        self._tts = ElevenLabsTTSStreamer(
            self._cfg,
            self._hub.output,
            on_busy_change=self._hub.set_tts_busy,
        )
        self._chunker = _DeltaTextChunker(
            self._tts.speak,
            flush_chars=self._cfg.elevenlabs_tts_flush_chars,
        )
        self._openai = OpenAIRealtimeManager(
            self._cfg,
            on_text_delta=self._chunker.feed,
            on_response_started=self._on_response_started,
            on_response_done=self._on_response_done,
            on_user_transcript=self._on_user_transcript,
        )

        self._active = False
        self._noise_calibration_active = False
        self._last_wake_time = 0.0
        self._last_end_session_time = 0.0
        self._end_session_cooldown_sec = 2.0
        self._stop = threading.Event()

        self._btn = SmartButton(
            pin=self._cfg.button_pin,
            on_single_click=self._trigger_wake,
            on_double_click=self._trigger_end_session,
            on_hold=self._trigger_interrupt,
            on_long_hold=self._trigger_noise_calibration,
        )

    def run(self) -> None:
        self._setup_signal_handlers()
        self._tts.start()
        self._hub.start()
        self._hotword.start()
        self._emotion.send_system_state("ready")
        log.info("Shany realtime lista: di 'Hola Shany'")

        try:
            self._main_loop()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        self._trigger_end_session()
        self._tts.shutdown()
        self._hotword.shutdown()
        self._hub.shutdown()
        self._emotion.send_ui_state("idle")

    def _main_loop(self) -> None:
        while not self._stop.is_set():
            frame = self._hotword.get_frame()
            if self._active or self._noise_calibration_active:
                time.sleep(0.02)
                continue
            confidence = self._hotword.check_wake(frame)
            if confidence is not None:
                log.info("[wake] hola_shany (conf %.3f)", confidence)
                self._trigger_wake()

    def _trigger_wake(self) -> None:
        if self._active or self._noise_calibration_active:
            return
        if time.time() - self._last_end_session_time < self._end_session_cooldown_sec:
            return
        log.info("Realtime Wake: abriendo sesion")
        self._active = True
        self._last_wake_time = time.time()
        self._emotion.send_ui_state("listening")
        self._chunker.reset()
        self._tts.cancel()
        self._openai.start()
        self._hub.attach_input_callback(self._openai.submit_audio)
        self._hub.note_agent_turn_started()
        self._tts.speak(SHANY_INITIAL_GREETING)
        self._hub.note_agent_text_received()

    def _trigger_interrupt(self) -> None:
        if not self._active:
            return
        log.info("Realtime Interrupt: cortando respuesta")
        self._chunker.reset()
        self._tts.cancel()
        self._openai.cancel_response()
        self._hub.interrupt()
        self._emotion.send_ui_state("listening")

    def _trigger_end_session(self) -> None:
        if not self._active:
            return
        log.info("Realtime End: cerrando sesion")
        self._active = False
        self._last_end_session_time = time.time()
        self._hub.detach_input_callback()
        self._chunker.reset()
        self._tts.cancel()
        self._openai.stop()
        self._hub.interrupt()
        self._emotion.send_ui_state("idle")

    def _trigger_noise_calibration(self) -> None:
        if self._active:
            log.info("Calibracion VAD ignorada: hay una sesion activa")
            return
        if self._noise_calibration_active:
            return

        def pulse_ready_led(stop_event: threading.Event) -> None:
            # Reutiliza estados que el ESP32 ya entiende para indicar
            # calibracion sin cambiar firmware.
            while not stop_event.is_set():
                self._emotion.send_system_state("booting")
                stop_event.wait(0.35)
                self._emotion.send_system_state("ready")
                stop_event.wait(0.90)

        def worker() -> None:
            self._noise_calibration_active = True
            stop_led = threading.Event()
            log.info(
                "Calibracion VAD iniciada: manten silencio cerca de Shany durante %.1f s",
                self._cfg.vad_calibration_secs,
            )
            try:
                threading.Thread(
                    target=pulse_ready_led,
                    args=(stop_led,),
                    daemon=True,
                    name="vad-calibration-led",
                ).start()
                self._emotion.send_ui_state("listening")
                result = self._hub.calibrate_noise_floor(self._cfg.vad_calibration_secs)
                log.info("Calibracion VAD terminada: %s", result)
            finally:
                stop_led.set()
                self._emotion.send_system_state("ready")
                self._emotion.send_ui_state("idle")
                self._noise_calibration_active = False

        threading.Thread(target=worker, daemon=True, name="vad-calibration").start()

    def _on_response_started(self) -> None:
        self._hub.note_agent_turn_started()

    def _on_response_done(self) -> None:
        self._chunker.flush()
        self._hub.note_agent_text_received()

    def _on_user_transcript(self, transcript: str) -> None:
        log.info("User(OpenAI): %s", transcript)

    def _setup_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            log.info("Senal %s recibida; apagando", signum)
            self._stop.set()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

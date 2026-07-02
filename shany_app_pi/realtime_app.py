"""Orquestador principal: OpenAI Realtime + ElevenLabs TTS."""

from __future__ import annotations

import logging
import random
import signal
import threading
import time
import unicodedata
from typing import Optional

from shany_app_pi.audio_hub import AudioHub
from shany_app_pi.config import ShanyConfig
from shany_app_pi.elevenlabs_tts_streamer import ElevenLabsTTSStreamer
from shany_app_pi.emotion_bridge import EmotionBridge
from shany_app_pi.hardware_button import SmartButton
from shany_app_pi.openai_realtime_manager import OpenAIRealtimeManager
from shany_app_pi.shany_prompt import SHANY_INITIAL_GREETING_PARTS

log = logging.getLogger(__name__)

USER_FAREWELL_MESSAGE = (
    "Gracias por conversar conmigo. Me alegro mucho de haber estado contigo un ratito. "
    "Ahora voy a descansar. Chau."
)

SESSION_LIMIT_FAREWELL_MESSAGE = (
    "Me encanto conversar contigo. Ahora tengo que ir a acompanar a mas ninos, "
    "pero gracias por compartir este ratito conmigo. Te mando una sonrisa grande. Chau."
)


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
        self._tts = ElevenLabsTTSStreamer(
            self._cfg,
            self._hub.output,
            on_busy_change=self._hub.set_tts_busy,
        )
        self._chunker = _DeltaTextChunker(
            self._speak_with_emotion,
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
        self._manual_end_hotword_block_sec = 45.0
        self._wake_allowed_at = 0.0
        self._end_after_response = False
        self._farewell_in_progress = False
        self._session_soft_end_at = 0.0
        self._farewell_lock = threading.Lock()
        self._stop = threading.Event()

        self._btn = SmartButton(
            pin=self._cfg.button_pin,
            on_single_click=self._trigger_button_click,
            on_double_click=self._trigger_end_session,
            on_hold=self._trigger_interrupt,
            on_long_hold=self._trigger_noise_calibration,
        )

    def run(self) -> None:
        self._setup_signal_handlers()
        self._tts.start()
        self._hub.start()
        self._emotion.send_system_state("ready")
        self._wake_allowed_at = time.time() + self._cfg.startup_wake_grace_sec
        log.info("Shany realtime lista: inicia con el boton")

        try:
            self._main_loop()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        self._trigger_end_session()
        self._tts.shutdown()
        self._hub.shutdown()
        self._emotion.send_ui_state("idle")

    def _main_loop(self) -> None:
        while not self._stop.is_set():
            if self._should_start_session_farewell():
                self._start_farewell(
                    reason="session_soft_limit",
                    message=SESSION_LIMIT_FAREWELL_MESSAGE,
                )
            time.sleep(0.2)

    def _trigger_button_click(self) -> None:
        if self._active or self._farewell_in_progress:
            log.info("Boton: click simple ignorado con sesion activa")
            return
        self._trigger_wake(from_button=True)

    def _trigger_wake(self, *, from_button: bool = False) -> None:
        if self._active or self._noise_calibration_active or self._farewell_in_progress:
            return
        if not from_button and time.time() < self._wake_allowed_at:
            log.info("Wake ignorado: sistema aun armando hotword")
            return
        if time.time() - self._last_end_session_time < self._end_session_cooldown_sec:
            return
        log.info("Realtime Wake: abriendo sesion")
        self._active = True
        self._last_wake_time = time.time()
        self._session_soft_end_at = self._compute_session_soft_end_at(self._last_wake_time)
        self._emotion.send_ui_state("listening")
        self._chunker.reset()
        self._tts.cancel()
        self._openai.start()
        self._hub.attach_input_callback(self._openai.submit_audio)
        self._hub.note_agent_turn_started()
        self._end_after_response = False
        self._farewell_in_progress = False
        log.info(
            "Sesion Shany: cierre suave programado en %.1f min",
            max(0.0, self._session_soft_end_at - self._last_wake_time) / 60.0,
        )
        self._speak_initial_greeting()
        self._hub.note_agent_text_received()

    def _trigger_interrupt(self) -> None:
        if not self._active or self._farewell_in_progress:
            return
        log.info("Realtime Interrupt: cortando respuesta")
        self._chunker.reset()
        self._tts.cancel()
        self._openai.cancel_response()
        self._hub.interrupt()
        self._emotion.send_ui_state("listening")

    def _trigger_end_session(self) -> None:
        if not self._active and not self._farewell_in_progress:
            return
        log.info("Realtime End: cerrando sesion")
        self._active = False
        self._farewell_in_progress = False
        self._end_after_response = False
        self._session_soft_end_at = 0.0
        self._last_end_session_time = time.time()
        self._hub.detach_input_callback()
        self._chunker.reset()
        self._hub.drop_agent_audio_window(3.0)
        self._hub.interrupt()
        self._tts.cancel()
        self._openai.stop()
        self._emotion.send_ui_state("idle")
        self._wake_allowed_at = time.time() + self._manual_end_hotword_block_sec

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
        self._emotion.send_ui_state("idle")
        self._hub.note_agent_turn_started()

    def _on_response_done(self) -> None:
        self._chunker.flush()
        self._hub.note_agent_text_received()
        if self._end_after_response:
            threading.Timer(8.0, self._trigger_end_session).start()

    def _on_user_transcript(self, transcript: str) -> None:
        log.info("User(OpenAI): %s", transcript)
        lower = self._normalize_text(transcript)
        end_markers = (
            "chao",
            "chau",
            "adios",
            "adiós",
            "me tengo que ir",
            "hasta luego",
            "terminar conversacion",
            "cortar conversacion",
            "apagate",
            "apágate",
            "duermete",
            "duérmete",
            "anda a dormir",
        )
        if any(marker in lower for marker in end_markers):
            log.info("Fin de sesion solicitado por voz")
            threading.Thread(
                target=self._start_farewell,
                kwargs={"reason": "voice_farewell", "message": USER_FAREWELL_MESSAGE},
                daemon=True,
                name="voice-farewell",
            ).start()

    def _compute_session_soft_end_at(self, started_at: float) -> float:
        base = max(60.0, float(self._cfg.session_soft_limit_sec))
        jitter = max(0.0, float(self._cfg.session_soft_limit_jitter_sec))
        return started_at + base + (random.uniform(0.0, jitter) if jitter else 0.0)

    def _should_start_session_farewell(self) -> bool:
        return (
            self._active
            and not self._farewell_in_progress
            and self._session_soft_end_at > 0.0
            and time.time() >= self._session_soft_end_at
            and not self._hub.agent_is_speaking()
        )

    def _start_farewell(self, *, reason: str, message: str) -> None:
        with self._farewell_lock:
            if not self._active or self._farewell_in_progress:
                return
            self._active = False
            self._farewell_in_progress = True
            self._end_after_response = False
            self._session_soft_end_at = 0.0
            self._last_end_session_time = time.time()

        log.info("Despedida Shany iniciada (%s)", reason)
        self._hub.detach_input_callback()
        self._chunker.reset()
        self._openai.cancel_response()
        self._openai.stop()
        self._tts.cancel()
        self._hub.interrupt()
        self._emotion.set_emotion(
            {
                "emotion": "alegria_suave",
                "intensity": 0.78,
                "duration_ms": 18000,
                "blink": True,
            }
        )
        self._emotion.send_ui_state("idle")
        self._tts.speak(message)
        threading.Thread(
            target=self._finish_farewell_when_quiet,
            args=(reason,),
            daemon=True,
            name="farewell-close",
        ).start()

    def _finish_farewell_when_quiet(self, reason: str) -> None:
        min_wait_sec = 2.0
        max_wait_sec = 22.0
        started_at = time.time()
        time.sleep(min_wait_sec)
        while (time.time() - started_at) < max_wait_sec:
            if not self._hub.agent_is_speaking():
                break
            time.sleep(0.2)

        log.info("Despedida Shany terminada (%s)", reason)
        self._tts.cancel()
        self._hub.interrupt()
        self._emotion.send_ui_state("idle")
        self._wake_allowed_at = time.time() + self._manual_end_hotword_block_sec
        with self._farewell_lock:
            self._farewell_in_progress = False
            self._active = False

    _EMOTION_PATTERNS = {
        "empatia": [
            ("entiendo que te sientas", 3.5),
            ("es normal sentirse", 3.0),
            ("no estas solo", 3.0),
            ("aqui contigo", 3.0),
            ("siento mucho", 3.0),
            ("se que es dificil", 3.0),
            ("no pasa nada", 2.5),
            ("te acompa", 2.5),
            ("muy valiente", 2.5),
            ("puedes contar conmigo", 3.0),
            ("respir", 1.5),
            ("lamento", 2.0),
            ("triste", 2.0),
            ("dolor", 1.5),
            ("cansad", 1.5),
            ("preocup", 1.5),
            ("miedo", 1.5),
            ("llorar", 1.5),
            ("valiente", 1.5),
            ("abrazo", 1.5),
            ("dificil", 0.8),
            ("duro", 0.7),
            ("calma", 1.0),
            ("despacito", 1.0),
        ],
        "alegria_suave": [
            ("que idea tan", 3.0),
            ("que divertido", 3.0),
            ("me encanta", 2.5),
            ("que bueno", 2.5),
            ("vamos a imaginar", 3.0),
            ("vamos a inventar", 3.0),
            ("cerremos los ojos", 2.0),
            ("habia una vez", 2.5),
            ("genial", 2.0),
            ("maravilloso", 2.0),
            ("increible", 2.0),
            ("fantastic", 2.0),
            ("divertid", 1.5),
            ("alegr", 1.5),
            ("feliz", 1.5),
            ("content", 1.5),
            ("aventura", 1.5),
            ("magic", 1.5),
            ("imaginemos", 1.5),
            ("inventemos", 1.5),
            ("sonrisa", 1.5),
            ("bravo", 1.5),
        ],
        "duda": [
            ("no entendi", 3.0),
            ("te refieres", 2.5),
            ("quieres decir", 2.5),
            ("puedes repetir", 2.0),
            ("como asi", 2.0),
        ],
        "sorpresa": [
            ("wow", 2.0),
            ("oh", 1.5),
            ("sorpresa", 2.5),
            ("mira eso", 2.0),
        ],
    }

    _DAMPENERS = {
        "empatia": ["que divertido", "genial", "juguemos", "chiste"],
        "alegria_suave": ["lamento", "triste", "dolor", "llorar", "miedo"],
    }

    _EMOTION_THRESHOLD = 2.4

    def _speak_with_emotion(self, text: str) -> bool:
        self._detect_emotion(text)
        return self._tts.speak(text)

    def _speak_initial_greeting(self) -> None:
        self._emotion.set_emotion(
            {
                "emotion": "alegria_suave",
                "intensity": 0.82,
                "duration_ms": 30000,
                "blink": True,
            }
        )
        for part in SHANY_INITIAL_GREETING_PARTS:
            self._tts.speak(part)

    def _detect_emotion(self, text: str) -> None:
        lower = (
            text.lower()
            .replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("ñ", "n")
        )
        scores: dict[str, float] = {}
        for emotion, patterns in self._EMOTION_PATTERNS.items():
            score = sum(weight for phrase, weight in patterns if phrase in lower)
            for dampener in self._DAMPENERS.get(emotion, []):
                if dampener in lower:
                    score *= 0.6
            scores[emotion] = score

        best = max(scores, key=scores.get)
        best_score = scores[best]
        if best_score < self._EMOTION_THRESHOLD:
            return

        intensity = min(0.55 + (best_score - self._EMOTION_THRESHOLD) * 0.05, 0.85)
        self._emotion.set_emotion(
            {
                "emotion": best,
                "intensity": round(intensity, 2),
                "duration_ms": 16000,
                "blink": True,
            }
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text.lower())
        return "".join(
            ch for ch in normalized if unicodedata.category(ch) != "Mn"
        )

    def _setup_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            log.info("Senal %s recibida; apagando", signum)
            self._stop.set()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

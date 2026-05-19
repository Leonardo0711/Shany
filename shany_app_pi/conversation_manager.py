"""
conversation_manager.py — Gestión de sesiones con ElevenLabs.

Maneja el ciclo de vida de una conversación (crear, iniciar, cerrar)
y un monitor de inactividad que cierra la sesión tras un timeout.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation

if TYPE_CHECKING:
    from shany_app_pi.audio_hub import HubAudioInterface
    from shany_app_pi.config import ShanyConfig
    from shany_app_pi.emotion_bridge import EmotionBridge

log = logging.getLogger(__name__)


class ConversationManager:
    """
    Gestiona sesiones de conversación con ElevenLabs.

    Thread-safe: todas las lecturas/escrituras del estado interno
    pasan por ``_lock``.
    """

    def __init__(
        self,
        config: ShanyConfig,
        audio_interface: HubAudioInterface,
        emotion_bridge: EmotionBridge,
        on_agent_response: Optional[Callable[[], None]] = None,
    ) -> None:
        self._cfg = config
        self._audio_interface = audio_interface
        self._emotion = emotion_bridge
        self._on_agent_response = on_agent_response
        self._client = ElevenLabs(api_key=config.api_key)

        self._lock = threading.Lock()
        self._conversation: Optional[Conversation] = None
        self._active: bool = False
        self._last_interaction: float = 0.0
        self._stop = threading.Event()

    # ── Propiedades thread-safe ──────────────────────────────────

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def conversation(self) -> Optional[Conversation]:
        with self._lock:
            return self._conversation

    @property
    def last_interaction_time(self) -> float:
        with self._lock:
            return self._last_interaction

    # ── Acciones ─────────────────────────────────────────────────

    def touch(self) -> None:
        """Actualiza el timestamp de última interacción."""
        with self._lock:
            self._last_interaction = time.time()

    def send_user_message(self, text: str) -> bool:
        """Envia texto del usuario a ElevenLabs como turno ya transcrito."""
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return False

        with self._lock:
            conv = self._conversation
            active = self._active

        if conv is None or not active:
            log.info("Mensaje STT ignorado: no hay sesion activa")
            return False

        try:
            log.info("User(STT): %s", cleaned)
            conv.send_user_message(cleaned)
            self.touch()
            return True
        except Exception as exc:
            log.warning("No se pudo enviar user_message a ElevenLabs: %s", exc)
            return False

    def start_session(self) -> None:
        """Crea y arranca una nueva sesión de conversación."""
        with self._lock:
            if self._active:
                return
            conv = self._create_conversation()
            self._conversation = conv
            self._active = True
            self._last_interaction = time.time()

        conv.start_session()
        log.info("Sesión iniciada")

        # Hilo que espera el fin de sesión
        threading.Thread(
            target=self._waiter, args=(conv,), daemon=True, name="conv-waiter"
        ).start()

    def end_session(self, reason: str = "") -> None:
        """Cierra la sesión activa."""
        with self._lock:
            conv = self._conversation

        if conv is None:
            return

        label = f" ({reason})" if reason else ""
        log.info("Cerrando sesión%s …", label)

        try:
            conv.end_session()
        except Exception:
            pass

        with self._lock:
            self._active = False
            self._conversation = None

    def start_inactivity_monitor(self) -> None:
        """Lanza un hilo daemon que cierra la sesión por inactividad."""
        threading.Thread(
            target=self._inactivity_loop, daemon=True, name="inactivity-monitor"
        ).start()

    def shutdown(self) -> None:
        """Señala a los hilos internos que deben detenerse."""
        self._stop.set()
        self.end_session("shutdown")
        log.info("ConversationManager apagado")

    # ── Detección local de emociones (scoring ponderado) ─────────

    # Cada patrón: (frase, peso). Frases más específicas pesan más.
    # Múltiples matches acumulan score → más contexto emocional = más certeza.
    _EMOTION_PATTERNS = {
        "empatia": [
            # Frases completas (alta confianza)
            ("entiendo que te sientas", 3.5),
            ("es normal sentirse", 3.0),
            ("no estás solo", 3.0),
            ("aquí contigo", 3.0),
            ("siento mucho", 3.0),
            ("sé que es difícil", 3.0),
            ("no pasa nada", 2.5),
            ("echar de menos", 2.5),
            ("te acompañ", 2.5),
            ("muy valiente", 2.5),
            ("aquí para escucharte", 3.0),
            ("puedes contar conmigo", 3.0),
            ("respir", 1.5),
            # Palabras con contexto (confianza media)
            ("lamento", 2.0), ("tristeza", 2.0), ("dolor", 1.5),
            ("cansad", 1.5), ("preocup", 1.5), ("extrañ", 1.5),
            ("miedo", 1.5), ("llorar", 1.5), ("valiente", 1.5),
            ("abrazo", 1.5), ("soledad", 1.5),
            # Señales suaves (confianza baja, necesitan acumularse)
            ("difícil", 0.8), ("duro", 0.7), ("complicado", 0.7),
        ],
        "alegria_suave": [
            # Frases completas
            ("qué idea tan", 3.0), ("qué divertido", 3.0),
            ("me encanta", 2.5), ("qué bueno", 2.5),
            ("vamos a imaginar", 3.0), ("vamos a inventar", 3.0),
            ("cerremos los ojos", 2.0), ("había una vez", 2.5),
            ("qué nombre le ponemos", 2.5),
            # Palabras positivas
            ("genial", 2.0), ("maravilloso", 2.0), ("increíble", 2.0),
            ("fantástic", 2.0), ("divertid", 1.5), ("alegr", 1.5),
            ("feliz", 1.5), ("contenta", 1.5), ("contento", 1.5),
            ("aventura", 1.5), ("mágic", 1.5), ("imaginemos", 1.5),
            ("inventemos", 1.5), ("estrellita", 1.5),
            ("súper", 1.0), ("excelente", 1.5), ("bravo", 1.5),
        ],
    }

    # Dampeners: reducen el score si hay señales contradictorias
    _DAMPENERS = {
        "empatia": ["pero vamos", "sin embargo", "aunque podemos", "divertir"],
        "alegria_suave": ["lamento", "triste", "dolor", "llorar", "miedo"],
    }

    _EMOTION_THRESHOLD = 2.5  # Score mínimo para activar una emoción

    def _detect_emotion(self, text: str) -> None:
        """
        Analiza el texto del agente con scoring ponderado.
        Frases más largas y específicas pesan más.
        Múltiples coincidencias acumulan confianza.
        """
        lower = text.lower()
        scores: dict[str, float] = {}

        for emotion, patterns in self._EMOTION_PATTERNS.items():
            score = sum(w for phrase, w in patterns if phrase in lower)

            # Dampeners: reducir score si hay señales contradictorias
            for dampener in self._DAMPENERS.get(emotion, []):
                if dampener in lower:
                    score *= 0.6

            scores[emotion] = score

        # Seleccionar la emoción con mayor score
        best = max(scores, key=scores.get)
        best_score = scores[best]

        if best_score >= self._EMOTION_THRESHOLD:
            # Intensidad proporcional al score (0.55 a 0.80)
            intensity = min(0.55 + (best_score - self._EMOTION_THRESHOLD) * 0.04, 0.80)
            self._emotion.set_emotion({
                "emotion": best,
                "intensity": round(intensity, 2),
                "duration_ms": 30000,  # 30 seg — se corta cuando Shany calla
                "blink": True,
            })

    # ── Internos ─────────────────────────────────────────────────

    def _create_conversation(self) -> Conversation:

        def on_agent(resp: str) -> None:
            log.info("Agent: %s", resp)
            self.touch()
            if self._on_agent_response is not None:
                self._on_agent_response()
            # Detección local de emoción (cero latencia)
            self._detect_emotion(resp)

        def on_user(txt: str) -> None:
            log.info("User: %s", txt)
            self.touch()

        return Conversation(
            self._client,
            self._cfg.agent_id,
            requires_auth=bool(self._cfg.api_key),
            audio_interface=self._audio_interface,
            callback_agent_response=on_agent,
            callback_user_transcript=on_user,
        )

    def _waiter(self, conv: Conversation) -> None:
        try:
            conv.wait_for_session_end()
        except Exception:
            pass
        finally:
            # ESP32: cara de reposo al terminar sesión natural
            self._emotion.send_ui_state("idle")
            with self._lock:
                self._active = False
                self._conversation = None
            log.info("Sesión terminada. Di 'Hola Shany' para iniciar otra.")

    def _inactivity_loop(self) -> None:
        timeout = self._cfg.inactivity_timeout_sec
        while not self._stop.is_set():
            time.sleep(1)
            if not self.is_active:
                continue
            if time.time() - self.last_interaction_time > timeout:
                self.end_session("timeout")

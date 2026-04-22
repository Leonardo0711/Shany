"""
conversation_manager.py — Gestión de sesiones con ElevenLabs.

Maneja el ciclo de vida de una conversación (crear, iniciar, cerrar)
y un monitor de inactividad que cierra la sesión tras un timeout.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Optional

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
    ) -> None:
        self._cfg = config
        self._audio_interface = audio_interface
        self._emotion = emotion_bridge
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

    # ── Internos ─────────────────────────────────────────────────

    def _create_conversation(self) -> Conversation:
        from elevenlabs.conversational_ai.conversation import ClientTools

        def on_agent(resp: str) -> None:
            log.info("Agent: %s", resp)
            self.touch()

        def on_user(txt: str) -> None:
            log.info("User: %s", txt)
            self.touch()

        # Configurar Herramientas de Cliente (Fase 1: Emociones)
        client_tools = ClientTools()
        client_tools.register(
            "setEmotion", 
            lambda params: self._emotion.set_emotion(params)
        )

        return Conversation(
            self._client,
            self._cfg.agent_id,
            requires_auth=bool(self._cfg.api_key),
            audio_interface=self._audio_interface,
            callback_agent_response=on_agent,
            callback_user_transcript=on_user,
            client_tools=client_tools,
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

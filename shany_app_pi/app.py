"""
app.py — Orquestador principal de Shany.

Conecta AudioHub, HotwordEngine y ConversationManager en un loop
principal con dos estados: STANDBY y CONVERSATION.
"""

from __future__ import annotations

import logging
import signal
import time
from typing import Optional

from shany_app_pi.audio_hub import AudioHub, HubAudioInterface
from shany_app_pi.config import ShanyConfig
from shany_app_pi.conversation_manager import ConversationManager
from shany_app_pi.hotword_engine import HotwordEngine
from shany_app_pi.hardware_button import SmartButton

log = logging.getLogger(__name__)


class ShanyApp:
    """
    Aplicación principal de Shany.

    Uso::

        app = ShanyApp()
        app.run()          # bloquea en el loop principal
    """

    def __init__(self, config: Optional[ShanyConfig] = None) -> None:
        self._cfg = config or ShanyConfig()
        self._cfg.validate()

        # ── Componentes ──────────────────────────────────────────
        self._hub = AudioHub(self._cfg)
        self._audio_interface = HubAudioInterface(self._hub)
        self._hotword = HotwordEngine(self._cfg, self._hub)
        self._conv = ConversationManager(self._cfg, self._audio_interface)

        # Anti-solapamiento: evita que "shany" dentro de "hola shany"
        # dispare una interrupción justo después del wake
        self._last_wake_time: float = 0.0
        # Cooldown: evita doble detección de interrupt
        self._last_interrupt_time: float = 0.0
        self._interrupt_cooldown_sec: float = 3.0

        # Botón Físico de Control (Hardware fallback)
        self._btn = SmartButton(
            pin=self._cfg.button_pin,
            on_single_click=self._trigger_wake,
            on_double_click=self._trigger_end_session,
            on_hold=self._trigger_interrupt
        )

    # ── Ciclo de vida ────────────────────────────────────────────

    def run(self) -> None:
        """Arranca todos los componentes y entra en el loop principal."""
        self._setup_signal_handlers()
        self._hub.start()
        self._hotword.start()
        self._conv.start_inactivity_monitor()

        log.info(
            "Standby: di 'Hola Shany'. "
            "En conversación: di 'Shany' para interrumpir SIN cortar sesión."
        )

        try:
            self._main_loop()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Apaga todos los componentes de forma ordenada."""
        log.info("Apagando Shany …")
        self._conv.shutdown()
        self._hotword.shutdown()
        self._hub.shutdown()

    # ── Loop principal ───────────────────────────────────────────

    def _main_loop(self) -> None:
        cfg = self._cfg
        hotword = self._hotword
        conv = self._conv
        hub = self._hub

        while True:
            frame = hotword.get_frame()
            now = time.time()

            # ── STANDBY ──────────────────────────────────────────
            if not conv.is_active:
                confidence = hotword.check_wake(frame)
                if confidence is not None:
                    log.info("[wake] hola_shany (vía micrófono) (conf %.3f)", confidence)
                    self._trigger_wake()
                continue

            # ── CONVERSACIÓN ─────────────────────────────────────
            # Bloqueo post-wake para evitar falso interrupt
            if now - self._last_wake_time < cfg.wake_to_interrupt_block_sec:
                continue

            # Cooldown post-interrupt para evitar doble detección
            if now - self._last_interrupt_time < self._interrupt_cooldown_sec:
                continue

            # (Desactivado por petición del usuario: La interrupción vocal de "Shany" 
            # ya no cortará a la IA. Ahora se confía puramente en el botón físico).
            # confidence = hotword.check_interrupt(frame)
            # if confidence is not None:
            #    log.info("[interrupt] shany (vía micrófono) (conf %.3f)", confidence)
            #    self._trigger_interrupt()

    # ── Triggers de Control (Audio y Botón) ──────────────────────

    def _trigger_wake(self) -> None:
        """Inicia la sesión (equivalente a 'Hola Shany')."""
        if not self._conv.is_active:
            log.info("Trigger Wake: Abriendo sesión")
            self._last_wake_time = time.time()
            self._conv.start_session()

    def _trigger_interrupt(self) -> None:
        """Corta al agente para escuchar (equivalente a 'Shany')."""
        if not self._conv.is_active:
            return

        log.info("Trigger Interrupt: Forzando escucha")
        self._last_interrupt_time = time.time()

        # 1) Cortar playback local sin cerrar sesión
        try:
            c = self._conv.conversation
            if c is not None:
                c.audio_interface.interrupt()
        except Exception:
            self._hub.interrupt()

        # 2) Ignorar audio del agente un rato
        self._hub.drop_agent_audio_window(self._cfg.drop_agent_audio_secs)

        # 3) Dejar pasar tu voz al agente
        self._hub.force_listen_window(self._cfg.force_listen_secs)

        self._conv.touch()
        
    def _trigger_end_session(self) -> None:
        """Cierra la sesión de golpe (Double Click)."""
        if self._conv.is_active:
            log.info("Trigger End Session: Cerrando por control manual")
            self._conv.end_session("manual_double_click")

    # ── Signal handling ──────────────────────────────────────────

    def _setup_signal_handlers(self) -> None:
        def handler(sig, frame):
            self.shutdown()
            raise SystemExit(0)

        signal.signal(signal.SIGINT, handler)

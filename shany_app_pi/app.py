"""
app.py — Orquestador principal de Shany.

Conecta AudioHub, HotwordEngine y ConversationManager en un loop
principal con dos estados: STANDBY y CONVERSATION.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Optional

from shany_app_pi.audio_hub import AudioHub, HubAudioInterface
from shany_app_pi.config import ShanyConfig
from shany_app_pi.conversation_manager import ConversationManager
from shany_app_pi.hotword_engine import HotwordEngine
from shany_app_pi.hardware_button import SmartButton
from shany_app_pi.emotion_bridge import EmotionBridge
from shany_app_pi.elevenlabs_stt import ElevenLabsTranscriber

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
        self._emotion = EmotionBridge()
        self._hub = AudioHub(self._cfg, visual_bridge=self._emotion)
        self._audio_interface = HubAudioInterface(self._hub)
        self._hotword = HotwordEngine(self._cfg, self._hub)
        self._conv = ConversationManager(
            self._cfg,
            self._audio_interface,
            self._emotion,
            on_agent_response=self._hub.note_agent_text_received,
        )
        self._stt: Optional[ElevenLabsTranscriber] = None
        if self._cfg.turn_stt_enabled:
            self._stt = ElevenLabsTranscriber(self._cfg, self._handle_stt_transcript)
            self._hub.attach_speech_segment_callback(self._stt.submit)

        # Anti-solapamiento: evita que "shany" dentro de "hola shany"
        # dispare una interrupción justo después del wake
        self._last_wake_time: float = 0.0
        # Cooldown: evita doble detección de interrupt
        self._last_interrupt_time: float = 0.0
        self._interrupt_cooldown_sec: float = 3.0
        # Cooldown post-cierre: evita que el doble-click reabra sesión
        self._last_end_session_time: float = 0.0
        self._end_session_cooldown_sec: float = 2.0
        self._noise_calibration_active: bool = False

        # Botón Físico de Control (Hardware fallback)
        self._btn = SmartButton(
            pin=self._cfg.button_pin,
            on_single_click=self._trigger_wake,
            on_double_click=self._trigger_end_session,
            on_hold=self._trigger_interrupt,
            on_long_hold=self._trigger_noise_calibration,
        )

    # ── Ciclo de vida ────────────────────────────────────────────

    def run(self) -> None:
        """Arranca todos los componentes y entra en el loop principal."""
        self._setup_signal_handlers()
        if self._stt is not None:
            self._stt.start()
        self._hub.start()
        self._hotword.start()
        self._conv.start_inactivity_monitor()

        log.info(
            "Standby: di 'Hola Shany'. "
            "En conversación: di 'Shany' para interrumpir SIN cortar sesión."
        )

        # ── Notificar al ESP32 que Shany está 100% lista ─────────
        # Este mensaje se envía DESPUÉS de que AudioHub, HotwordEngine
        # y el monitor de inactividad estén corriendo. Es el momento
        # real en que el usuario ya puede hablar.
        self._emotion.send_system_state("ready")
        log.info("Sistema listo → ESP32 notificado (system:ready)")

        try:
            self._main_loop()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Apaga todos los componentes de forma ordenada."""
        log.info("Apagando Shany …")
        if not self._conv.is_active:
            self._emotion.send_ui_state("idle")  # ESP32: cara de reposo
        self._hub.set_speech_capture_enabled(False)
        if self._stt is not None:
            self._stt.clear_pending()
            self._stt.shutdown()
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

            if self._noise_calibration_active:
                continue

            # ── STANDBY ──────────────────────────────────────────
            if not conv.is_active:
                hub.set_speech_capture_enabled(False)
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
        if self._noise_calibration_active:
            log.debug("Wake ignorado: calibración de ruido activa")
            return

        if not self._conv.is_active:
            # Cooldown: no reabrir si acabamos de cerrar por doble-click
            if time.time() - self._last_end_session_time < self._end_session_cooldown_sec:
                log.debug("Wake ignorado: cooldown post-cierre activo")
                return
            log.info("Trigger Wake: Abriendo sesión")
            self._last_wake_time = time.time()
            if self._stt is not None:
                self._stt.clear_pending()
            
            # ESP32: despertar visual inmediato (desacoplado para evitar bloqueos)
            threading.Thread(
                target=self._emotion.send_ui_state, 
                args=("listening",), 
                daemon=True
            ).start()
            
            try:
                self._conv.start_session()
                self._hub.set_speech_capture_enabled(True)
            except Exception as e:
                log.error("Fallo al iniciar sesión: %s", e)
                # Revertir visual a idle si falla el arranque
                threading.Thread(
                    target=self._emotion.send_ui_state, 
                    args=("idle",), 
                    daemon=True
                ).start()

    def _trigger_interrupt(self) -> None:
        """Corta al agente para escuchar (equivalente a 'Shany')."""
        if self._noise_calibration_active:
            return
        if not self._conv.is_active:
            return

        log.info("Trigger Interrupt: Forzando escucha")
        self._last_interrupt_time = time.time()

        # 1) Cortar playback local sin cerrar sesión
        self._hub.interrupt()

        # 2) Visual: solo el botón físico cambia la cara a "escuchando"
        self._emotion.send_ui_state("listening")

        # 3) Ignorar audio del agente un rato
        self._hub.drop_agent_audio_window(self._cfg.drop_agent_audio_secs)

        # 4) Dejar pasar tu voz al agente
        self._hub.force_listen_window(self._cfg.force_listen_secs)

        self._conv.touch()
        
    def _trigger_end_session(self) -> None:
        """Cierra la sesión de golpe (Double Click)."""
        if self._conv.is_active:
            log.info("Trigger End Session: Cerrando por control manual")
            self._last_end_session_time = time.time()
            self._hub.set_speech_capture_enabled(False)
            if self._stt is not None:
                self._stt.clear_pending()
            self._hub.interrupt()  # Limpiar audio pendiente
            self._emotion.send_ui_state("listening")  # Visual: feedback inmediato
            self._conv.end_session("manual_double_click")

    def _handle_stt_transcript(self, text: str) -> None:
        """Recibe texto de OpenAI STT y lo entrega al agente ElevenLabs."""
        if self._noise_calibration_active:
            return
        if not self._conv.is_active:
            return
        self._hub.note_agent_turn_started()
        if not self._conv.send_user_message(text):
            self._hub.cancel_agent_turn_wait()

    def _trigger_noise_calibration(self) -> None:
        """Calibra manualmente el ruido ambiente mediante hold largo."""
        if self._conv.is_active:
            log.info("Calibración VAD ignorada: hay una sesión activa")
            return
        if self._noise_calibration_active:
            return

        def pulse_ready_led(stop_event: threading.Event) -> None:
            # Reutiliza el par system:booting/system:ready que el ESP32 ya
            # entiende: produce el parpadeo cian existente sin tocar firmware.
            while not stop_event.is_set():
                self._emotion.send_system_state("booting")
                self._emotion.send_system_state("ready")
                stop_event.wait(1.25)

        def worker() -> None:
            self._noise_calibration_active = True
            stop_led = threading.Event()
            log.info(
                "Calibración VAD iniciada: mantén silencio cerca de Shany durante %.1f s",
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
                log.info("Calibración VAD terminada: %s", result)
            finally:
                stop_led.set()
                self._emotion.send_ui_state("idle")
                self._noise_calibration_active = False

        threading.Thread(target=worker, daemon=True, name="vad-calibration").start()

    # ── Signal handling ──────────────────────────────────────────

    def _setup_signal_handlers(self) -> None:
        def handler(sig, frame):
            self.shutdown()
            raise SystemExit(0)

        signal.signal(signal.SIGINT, handler)

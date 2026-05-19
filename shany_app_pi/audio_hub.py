"""
audio_hub.py — Capa de audio compartida.

Un solo micrófono y un solo speaker gestionados centralmente.
El hotword siempre recibe audio real; al agente se le envía
silencio mientras él mismo está hablando (anti-eco).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import pyaudio

if TYPE_CHECKING:
    from shany_app_pi.config import ShanyConfig
    from shany_app_pi.emotion_bridge import EmotionBridge

try:
    from elevenlabs.conversational_ai.conversation import AudioInterface
except Exception:
    AudioInterface = object  # type: ignore[assignment,misc]

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# AudioHub
# ─────────────────────────────────────────────────────────────────
class AudioHub:
    """
    Gestiona micrófono + speaker con un único PyAudio.

    - El hotword siempre recibe audio real del mic.
    - Cuando el agente habla, al agente se le manda silencio.
    - ``interrupt()`` invalida el audio pendiente sin cerrar sesión.
    """

    def __init__(self, config: ShanyConfig, visual_bridge: Optional[EmotionBridge] = None) -> None:
        self._cfg = config
        self._visual_bridge = visual_bridge
        self._pa = pyaudio.PyAudio()

        # Se delega al kernel (ALSA pcm.!default plug) la adaptación del 
        # sample rate (16kHz a 48kHz nativo) para evitar el IOError.
        self._input_device_idx = None
        self._output_device_idx = None

        log.info("AudioHub usará el dispositivo ALSA por defecto (con resampleo plug automático).")

        # Cola de frames para el hotword detector
        self._hotword_q: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=config.hotword_q_maxsize
        )

        # Cola mic -> agente/STT: (audio procesado real, VAD abierto)
        self._send_q: queue.Queue[tuple[bytes, bool]] = queue.Queue(
            maxsize=config.send_q_maxsize
        )
        self._input_callback: Optional[Callable[[bytes], None]] = None
        self._speech_segment_callback: Optional[Callable[[bytes, int], None]] = None
        self._cb_lock = threading.Lock()
        self._speech_capture_enabled: bool = False

        # Cola agente → speaker: (generation_id, chunk)
        self._out_q: queue.Queue[tuple[int, bytes]] = queue.Queue(
            maxsize=config.out_q_maxsize
        )
        self._stop = threading.Event()

        # Timestamps de gating y visuales
        self._last_output_ts: float = 0.0
        self._last_playback_write_ts: float = 0.0
        self._last_visual_emit: float = 0.0
        self._force_listen_until: float = 0.0
        self._drop_output_until: float = 0.0
        self._agent_turn_active: bool = False
        self._agent_turn_text_received: bool = False
        self._agent_turn_started_at: float = 0.0
        self._tts_busy: bool = False
        self._last_elevenlabs_silence_ts: float = 0.0
        self._elevenlabs_silence_burst_until: float = 0.0

        # Bloqueo extra del micrófono después de que Shany termina de hablar
        self._mic_guard_until: float = 0.0
        self._post_speech_mic_guard_sec: float = 0.85

        # Estado visual
        self._is_talking: bool = False
        self._speech_soft_closed: bool = False
        self._smoothed_mouth: float = 0.0
        self._window_rms_max: float = 0.0  # Max RMS entre envíos visuales

        # VAD local para filtrar ruido antes de enviar al agente
        self._mic_vad_active: bool = False
        self._mic_vad_hold_until: float = 0.0
        self._mic_vad_open_frames: int = 0
        self._mic_vad_close_frames: int = 0
        self._mic_vad_opened_at: float = 0.0
        self._mic_vad_peak_rms: float = 0.0
        self._vad_noise_threshold: int = self._load_vad_threshold()
        self._vad_close_threshold: int = self._compute_vad_close_threshold()

        # Calibración manual de ruido ambiente.
        self._calibration_lock = threading.Lock()
        self._calibrating_noise: bool = False
        self._calibration_rms_samples: list[float] = []
        log.info(
            "VAD iniciado (threshold=%d RMS pre-AGC, close=%d)",
            self._vad_noise_threshold,
            self._vad_close_threshold,
        )
        if config.turn_stt_enabled and not config.elevenlabs_audio_input_with_turn_stt:
            log.info("Audio real a ElevenLabs bloqueado; enviando silencio de mantenimiento")

        # AGC — Automatic Gain Control
        self._agc_gain: float = config.mic_gain  # Inicia en la ganancia base

        # Segmentacion para STT por turno. Corre en _sender_loop, no en el
        # callback de PyAudio.
        self._stt_preroll: deque[bytes] = deque(maxlen=config.turn_stt_preroll_frames)
        self._stt_frames: list[bytes] = []
        self._stt_segment_active: bool = False
        self._stt_segment_started_at: float = 0.0

        # Generación de playback (se incrementa en interrupt)
        self._playback_generation: int = 0
        self._playback_lock = threading.Lock()

        # Threads internos
        self._sender_thread = threading.Thread(
            target=self._sender_loop, daemon=True, name="audio-sender"
        )
        self._out_thread = threading.Thread(
            target=self._output_loop, daemon=True, name="audio-output"
        )

        self._in_stream: Optional[pyaudio.Stream] = None
        self._out_stream: Optional[pyaudio.Stream] = None
        self._running = False

    # ── Ciclo de vida ────────────────────────────────────────────

    def start(self) -> None:
        """Abre streams de entrada/salida y arranca los hilos."""
        if self._running:
            return

        chunk = self._cfg.chunk
        rate = self._cfg.sample_rate

        self._in_stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=rate,
            input=True,
            input_device_index=self._input_device_idx,
            frames_per_buffer=chunk,
            stream_callback=self._in_callback,
            start=True,
        )

        self._out_stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=rate,
            output=True,
            output_device_index=self._output_device_idx,
            frames_per_buffer=self._cfg.output_frames_per_buffer,
            start=True,
        )

        self._stop.clear()
        self._sender_thread.start()
        self._out_thread.start()
        self._running = True
        log.info("AudioHub iniciado (rate=%d, chunk=%d)", rate, chunk)

    def shutdown(self) -> None:
        """Detiene todo el hardware de audio de forma segura."""
        self._stop.set()

        for stream in (self._in_stream, self._out_stream):
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass

        try:
            self._pa.terminate()
        except Exception:
            pass

        log.info("AudioHub apagado")

    # ── Wiring con la conversación ───────────────────────────────

    def attach_input_callback(self, cb: Callable[[bytes], None]) -> None:
        """Conecta el callback que envía audio al agente."""
        with self._cb_lock:
            self._input_callback = cb

    def detach_input_callback(self) -> None:
        """Desconecta el callback del agente."""
        with self._cb_lock:
            self._input_callback = None

    def attach_speech_segment_callback(self, cb: Callable[[bytes, int], None]) -> None:
        """Conecta el callback que recibe frases completas para STT."""
        with self._cb_lock:
            self._speech_segment_callback = cb

    def detach_speech_segment_callback(self) -> None:
        """Desconecta el callback STT."""
        with self._cb_lock:
            self._speech_segment_callback = None

    def set_speech_capture_enabled(self, enabled: bool) -> None:
        """Activa/desactiva la captura local de frases para STT."""
        enabled = bool(enabled)
        if self._speech_capture_enabled == enabled:
            return
        self._speech_capture_enabled = enabled
        if enabled:
            self.pulse_elevenlabs_silence()
        if not enabled:
            self._reset_stt_segment()

    # ── Estado / gating ──────────────────────────────────────────

    def agent_is_speaking(self) -> bool:
        """Devuelve True si el agente está hablando o si estamos en cola de seguridad."""
        now = time.time()

        # Si el output loop marcó que está hablando, confiar en eso
        if self._is_talking:
            return True

        # Si todavía hay audio pendiente por reproducir
        if not self._out_q.empty():
            return True

        if self._tts_busy:
            return True

        # Protección corta después del último write real al parlante
        if (now - self._last_playback_write_ts) < self._post_speech_mic_guard_sec:
            return True

        # Protección explícita post-habla
        if now < self._mic_guard_until:
            return True

        # Mientras esperamos la respuesta del agente a un turno STT, no
        # capturamos mic. Si algo se cuelga, el timeout libera el gate.
        if self._agent_turn_active and not self._agent_turn_timed_out():
            return True

        return False

    def force_listen_window(self, secs: float) -> None:
        """Fuerza que el mic se envíe al agente durante *secs*."""
        self._force_listen_until = time.time() + max(0.0, secs)

    def drop_agent_audio_window(self, secs: float) -> None:
        """Ignora el audio del agente durante *secs*."""
        self._drop_output_until = time.time() + max(0.0, secs)

    def cancel_drop_window(self) -> None:
        """Cancela la ventana de drop (el agente empezó respuesta nueva)."""
        self._drop_output_until = 0.0

    def note_agent_turn_started(self) -> None:
        """Marca que ElevenLabs debe responder a un turno enviado por texto."""
        self._agent_turn_active = True
        self._agent_turn_text_received = False
        self._agent_turn_started_at = time.time()
        self.pulse_elevenlabs_silence()

    def note_agent_text_received(self) -> None:
        """Marca que ya llego el texto final del agente para este turno."""
        self._agent_turn_text_received = True

    def set_tts_busy(self, busy: bool) -> None:
        """Indica si ElevenLabs aun esta generando audio de la respuesta."""
        self._tts_busy = bool(busy)

    def cancel_agent_turn_wait(self) -> None:
        """Libera la espera de respuesta del agente sin tocar el audio."""
        self._finish_agent_turn()

    def _agent_turn_timed_out(self) -> bool:
        if not self._agent_turn_active:
            return False
        return (time.time() - self._agent_turn_started_at) > self._cfg.agent_turn_max_wait_sec

    def _finish_agent_turn(self) -> None:
        self._agent_turn_active = False
        self._agent_turn_text_received = False
        self._agent_turn_started_at = 0.0

    def pulse_elevenlabs_silence(self, secs: Optional[float] = None) -> None:
        """Mantiene vivo brevemente el websocket sin enviar audio real."""
        duration = self._cfg.elevenlabs_silence_burst_sec if secs is None else secs
        self._elevenlabs_silence_burst_until = time.time() + max(0.0, duration)

    # ── VAD / calibración ───────────────────────────────────────

    def calibrate_noise_floor(self, secs: Optional[float] = None) -> dict[str, float]:
        """
        Mide el ruido ambiente y guarda un nuevo umbral VAD persistente.

        Durante esta ventana nadie debería hablar cerca de Shany: queremos
        capturar el "silencio ruidoso" del entorno.
        """
        duration = secs if secs is not None else self._cfg.vad_calibration_secs
        duration = max(1.0, float(duration))

        with self._calibration_lock:
            if self._calibrating_noise:
                return {
                    "status": "already_running",
                    "threshold": float(self._vad_noise_threshold),
                }
            self._calibration_rms_samples = []
            self._calibrating_noise = True

        log.info("Calibrando ruido ambiente durante %.1f s ...", duration)
        time.sleep(duration)

        with self._calibration_lock:
            samples = list(self._calibration_rms_samples)
            self._calibrating_noise = False
            self._calibration_rms_samples = []

        if not samples:
            log.warning(
                "Calibración VAD sin muestras; se conserva threshold=%d",
                self._vad_noise_threshold,
            )
            return {
                "status": "no_samples",
                "threshold": float(self._vad_noise_threshold),
            }

        avg = float(np.mean(samples))
        pctl = float(np.percentile(samples, self._cfg.vad_calibration_percentile))
        threshold = self._clamp_vad_threshold(
            int(pctl * self._cfg.vad_calibration_multiplier)
        )

        self._vad_noise_threshold = threshold
        self._vad_close_threshold = self._compute_vad_close_threshold()
        self._save_vad_calibration(avg=avg, percentile=pctl, threshold=threshold)

        log.info(
            "Calibración VAD lista: avg=%.1f p%.0f=%.1f threshold=%d close=%d samples=%d",
            avg,
            self._cfg.vad_calibration_percentile,
            pctl,
            self._vad_noise_threshold,
            self._vad_close_threshold,
            len(samples),
        )
        return {
            "status": "ok",
            "avg": avg,
            "percentile": pctl,
            "threshold": float(self._vad_noise_threshold),
            "close_threshold": float(self._vad_close_threshold),
            "samples": float(len(samples)),
        }

    def _clamp_vad_threshold(self, value: int) -> int:
        return int(np.clip(value, self._cfg.vad_min_threshold, self._cfg.vad_max_threshold))

    def _compute_vad_close_threshold(self) -> int:
        return max(10, int(self._vad_noise_threshold * self._cfg.vad_close_ratio))

    def _load_vad_threshold(self) -> int:
        path = self._cfg.runtime_calibration_file
        fallback = self._clamp_vad_threshold(self._cfg.vad_noise_threshold)

        try:
            if not path.is_file():
                return fallback
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            threshold = int(data.get("vad_noise_threshold", fallback))
            threshold = self._clamp_vad_threshold(threshold)
            log.info("Calibración VAD cargada desde %s: threshold=%d", path, threshold)
            return threshold
        except Exception as exc:
            log.warning(
                "No se pudo cargar calibración VAD (%s); usando threshold=%d",
                exc,
                fallback,
            )
            return fallback

    def _save_vad_calibration(self, *, avg: float, percentile: float, threshold: int) -> None:
        path = self._cfg.runtime_calibration_file
        payload = {
            "vad_noise_threshold": threshold,
            "vad_close_threshold": self._vad_close_threshold,
            "noise_rms_avg": round(avg, 2),
            "noise_rms_percentile": round(percentile, 2),
            "percentile": self._cfg.vad_calibration_percentile,
            "multiplier": self._cfg.vad_calibration_multiplier,
            "saved_at_unix": int(time.time()),
        }

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        except Exception:
            log.exception("No se pudo guardar calibración VAD en %s", path)

    def _record_calibration_sample(self, raw_rms: float) -> None:
        if not self._calibrating_noise:
            return
        with self._calibration_lock:
            if self._calibrating_noise:
                self._calibration_rms_samples.append(raw_rms)

    def _update_vad_state(self, raw_rms: float, now_mono: float) -> bool:
        """
        VAD con histéresis: abre con varios frames consecutivos y cierra
        rápido, sin cortar finales de palabra.
        """
        if self._mic_vad_active:
            self._mic_vad_peak_rms = max(self._mic_vad_peak_rms, raw_rms)

        if raw_rms >= self._vad_noise_threshold:
            self._mic_vad_open_frames += 1
            self._mic_vad_close_frames = 0
        elif raw_rms < self._vad_close_threshold:
            self._mic_vad_close_frames += 1
            self._mic_vad_open_frames = 0
        else:
            # Zona intermedia: no abrir por ruido dudoso, pero tampoco cerrar
            # de golpe si ya venía hablando.
            self._mic_vad_open_frames = 0

        if not self._mic_vad_active:
            if self._mic_vad_open_frames >= self._cfg.vad_start_frames:
                self._mic_vad_active = True
                self._mic_vad_opened_at = now_mono
                self._mic_vad_peak_rms = raw_rms
                self._mic_vad_hold_until = now_mono + self._cfg.vad_hold_sec
                log.info(
                    "VAD abierto raw_rms=%.1f threshold=%d close=%d frames=%d",
                    raw_rms,
                    self._vad_noise_threshold,
                    self._vad_close_threshold,
                    self._cfg.vad_start_frames,
                )
        else:
            if raw_rms >= self._vad_close_threshold:
                self._mic_vad_hold_until = now_mono + self._cfg.vad_hold_sec
            elif (
                self._mic_vad_close_frames >= self._cfg.vad_stop_frames
                and now_mono >= self._mic_vad_hold_until
            ):
                duration = max(0.0, now_mono - self._mic_vad_opened_at)
                peak = self._mic_vad_peak_rms
                self._mic_vad_active = False
                self._mic_vad_open_frames = 0
                self._mic_vad_close_frames = 0
                self._mic_vad_opened_at = 0.0
                self._mic_vad_peak_rms = 0.0
                log.info(
                    "VAD cerrado raw_rms=%.1f close=%d duration=%.2fs peak=%.1f",
                    raw_rms,
                    self._vad_close_threshold,
                    duration,
                    peak,
                )

        return self._mic_vad_active

    # ── Output (agente → speaker) ────────────────────────────────

    def output(self, audio: bytes) -> None:
        """Encola audio del agente para reproducir."""
        now = time.time()

        if now < self._drop_output_until:
            # Aún en ventana de drop: descartar este chunk completamente
            return

        # Solo actualizar timestamps si realmente procesamos el audio
        self._last_output_ts = now
        self._drop_output_until = 0.0

        with self._playback_lock:
            gen = self._playback_generation

        step = self._cfg.output_slice_bytes
        for i in range(0, len(audio), step):
            piece = audio[i : i + step]
            try:
                self._out_q.put_nowait((gen, piece))
            except queue.Full:
                # Cola llena: descartamos sin bloquear para no frenar
                # el hilo de callback de ElevenLabs.
                pass

    def interrupt(self) -> None:
        """Corta el playback actual sin cerrar la sesión (solo audio)."""
        with self._playback_lock:
            self._playback_generation += 1

        # Vaciar cola de audio pendiente
        try:
            while True:
                self._out_q.get_nowait()
        except queue.Empty:
            pass

        # Reset estado de habla interno (sin tocar visuals —
        # los visuals los controla app.py desde los triggers del botón)
        if self._is_talking and self._visual_bridge:
            self._visual_bridge.send_speech_state(False)
            self._visual_bridge.send_speech_level(0.0)
        
        self._is_talking = False
        self._speech_soft_closed = False
        self._finish_agent_turn()
        self._smoothed_mouth = 0.0
        self._window_rms_max = 0.0
        self._mic_guard_until = 0.0
        self._last_playback_write_ts = 0.0
        log.debug("Playback interrumpido")

    # ── Hotword helper ───────────────────────────────────────────

    def hotword_next_frame(self) -> np.ndarray:
        """Bloquea hasta obtener el siguiente frame para el hotword."""
        return self._hotword_q.get()

    # ── Hilos internos ───────────────────────────────────────────

    def _should_send_real_mic(self) -> bool:
        now = time.time()

        # Si Shany está hablando o acaba de hablar, NO mandar mic real al agente
        if self.agent_is_speaking():
            return False

        # Solo permitir force_listen cuando ya no hay audio del agente
        if now < self._force_listen_until:
            return True

        return True

    def _find_device_index(self, name_part: str) -> Optional[int]:
        """Busca el índice de un dispositivo por nombre."""
        try:
            device_count = self._pa.get_device_count()
            for i in range(device_count):
                info = self._pa.get_device_info_by_index(i)
                if name_part.lower() in info.get("name", "").lower():
                    return i
        except Exception:
            pass
        return None

    def _output_loop(self) -> None:
        while not self._stop.is_set():
            try:
                # El timeout corto nos permite detectar el fin de habla por silencio
                gen, audio = self._out_q.get(timeout=0.1)
            except queue.Empty:
                # Si la cola está vacía y estábamos hablando, checar si ya pasó el umbral de silencio
                now = time.time()
                silence = now - self._last_playback_write_ts
                if self._is_talking and silence > self._cfg.output_soft_silence_sec:
                    log.debug("Pausa de audio detectada (silencio > %.0fms)", self._cfg.output_soft_silence_sec * 1000)

                    if not self._speech_soft_closed:
                        self._smoothed_mouth = 0.0
                        self._window_rms_max = 0.0
                        self._speech_soft_closed = True
                        if self._visual_bridge:
                            self._visual_bridge.send_speech_level(0.0)

                    can_finish_turn = (
                        not self._agent_turn_active
                        or self._agent_turn_text_received
                        or self._agent_turn_timed_out()
                    ) and not self._tts_busy
                    if not can_finish_turn or silence <= self._cfg.output_final_silence_sec:
                        continue

                    self._is_talking = False  # Marcar ANTES de enviar visual (evita repetir)
                    self._speech_soft_closed = False
                    self._finish_agent_turn()

                    # Mantener micrófono cerrado un poco más para evitar eco de última palabra
                    self._mic_guard_until = now + self._post_speech_mic_guard_sec

                    if self._visual_bridge:
                        self._visual_bridge.send_speech_state(False)
                        self._visual_bridge.send_speech_level(0.0)
                        self._visual_bridge.send_ui_state("listening")

                continue
            except Exception:
                continue

            with self._playback_lock:
                current_gen = self._playback_generation

            if gen != current_gen:
                continue

            try:
                if self._out_stream is not None:
                    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0

                    # ── Sincronía Visual (Lip Sync) ─────────────────
                    # Extraemos el RMS de la señal RAW (sin ganancia ni compresor)
                    # para que la boca siga la dinámica original y pueda cerrarse.
                    try:
                        if self._visual_bridge:
                            # 1) Detectar inicio de habla
                            if not self._is_talking:
                                self._visual_bridge.send_speech_state(True)
                                self._is_talking = True
                            self._speech_soft_closed = False

                            # Acumular RMS del chunk actual (raw)
                            rms = np.sqrt(np.mean(samples**2))
                            self._window_rms_max = max(self._window_rms_max, rms)

                            # 2) Emitir nivel de boca (~12 Hz)
                            now = time.time()
                            if (now - self._last_visual_emit) > 0.08:
                                window_rms = self._window_rms_max
                                self._window_rms_max = 0.0  # Reset ventana

                                # Zona muerta: ahora evaluamos el RMS natural sin amplificar
                                deadzone = 0.02
                                if window_rms < deadzone:
                                    mouth_raw = 0.0
                                else:
                                    mouth_raw = (window_rms - deadzone) * 5.0
                                    mouth_raw = min(max(mouth_raw, 0.0), 1.0)

                                # Suavizado asimétrico
                                if mouth_raw > self._smoothed_mouth:
                                    alpha = 0.7  # Abre natural y rápido
                                else:
                                    alpha = 0.85 # Cierra casi de inmediato al detectar silencio

                                self._smoothed_mouth = ((1.0 - alpha) * self._smoothed_mouth) + (alpha * mouth_raw)

                                # Piso de seguridad
                                if self._smoothed_mouth < 0.04:
                                    self._smoothed_mouth = 0.0

                                self._visual_bridge.send_speech_level(self._smoothed_mouth)
                                self._last_visual_emit = now
                    except Exception as ve:
                        log.warning("Error en lip-sync visual (audio no afectado): %s", ve)

                    # ── Pipeline de Salida (Calidad de Audio) ────────
                    # 1) Ganancia base
                    samples *= self._cfg.output_gain

                    # 2) Compresor suave (soft-knee) — mantiene volumen alto
                    #    sin el "crackle" del clipping duro. Las muestras fuertes
                    #    se comprimen suavemente en vez de cortarse de golpe.
                    threshold = self._cfg.output_comp_threshold
                    ratio = 0.4  # Compresión por encima del umbral
                    mask = np.abs(samples) > threshold
                    sign = np.sign(samples[mask])
                    excess = np.abs(samples[mask]) - threshold
                    samples[mask] = sign * (threshold + excess * ratio)

                    # 3) Suavizado anti-alias (media móvil de 3 muestras)
                    #    Reduce la aspereza del resampleo 16k→48k que hace ALSA.
                    kernel = np.array([0.2, 0.6, 0.2], dtype=np.float32)
                    samples = np.convolve(samples, kernel, mode='same')

                    # 4) Clip final de seguridad
                    np.clip(samples, -1.0, 1.0, out=samples)

                    # ── Reproducir audio (SIEMPRE, independiente de visual) ──
                    self._out_stream.write(samples.astype(np.float32).tobytes())

                    # Este timestamp representa sonido realmente enviado al parlante
                    self._last_playback_write_ts = time.time()
            except Exception as e:
                log.exception("Error en _output_loop: %s", e)

    def _sender_loop(self) -> None:
        while not self._stop.is_set():
            try:
                mic_bytes, voice_gate_open = self._send_q.get(timeout=0.25)
            except queue.Empty:
                continue

            with self._cb_lock:
                cb = self._input_callback
                speech_cb = self._speech_segment_callback

            allow_real_mic = self._should_send_real_mic()

            if self._cfg.turn_stt_enabled and speech_cb is not None:
                if not self._speech_capture_enabled:
                    if self._stt_segment_active or self._stt_preroll:
                        self._reset_stt_segment()
                else:
                    self._handle_stt_frame(
                        mic_bytes,
                        voice_gate_open and allow_real_mic,
                        speech_cb,
                    )

            if cb is None:
                continue

            silence = b"\x00" * len(mic_bytes)

            if (
                self._cfg.turn_stt_enabled
                and not self._cfg.elevenlabs_audio_input_with_turn_stt
            ):
                now = time.time()
                should_send_silence = (
                    now < self._elevenlabs_silence_burst_until
                    or (now - self._last_elevenlabs_silence_ts)
                    >= self._cfg.elevenlabs_silence_keepalive_sec
                )
                if should_send_silence:
                    self._last_elevenlabs_silence_ts = now
                    cb(silence)
                continue

            if allow_real_mic and (voice_gate_open or self._cfg.realtime_audio_passthrough):
                cb(mic_bytes)
            else:
                cb(silence)

    def _handle_stt_frame(
        self,
        mic_bytes: bytes,
        voice_frame: bool,
        speech_cb: Callable[[bytes, int], None],
    ) -> None:
        if not voice_frame:
            if self._stt_segment_active:
                self._finalize_stt_segment(speech_cb)
            else:
                self._stt_preroll.append(mic_bytes)
            return

        if not self._stt_segment_active:
            self._stt_segment_active = True
            self._stt_segment_started_at = time.monotonic()
            self._stt_frames = list(self._stt_preroll)
            log.info("STT segmento abierto preroll_frames=%d", len(self._stt_frames))

        self._stt_frames.append(mic_bytes)
        if (
            self._stt_segment_started_at
            and (time.monotonic() - self._stt_segment_started_at) >= self._cfg.elevenlabs_stt_max_audio_sec
        ):
            log.info(
                "STT segmento forzado por max %.1fs",
                self._cfg.elevenlabs_stt_max_audio_sec,
            )
            self._finalize_stt_segment(speech_cb)

    def _finalize_stt_segment(self, speech_cb: Callable[[bytes, int], None]) -> None:
        if not self._stt_frames:
            self._reset_stt_segment()
            return

        pcm = b"".join(self._stt_frames)
        duration = len(pcm) / float(self._cfg.sample_rate * 2)
        log.info("STT segmento cerrado duration=%.2fs bytes=%d", duration, len(pcm))
        self._reset_stt_segment()
        try:
            speech_cb(pcm, self._cfg.sample_rate)
        except Exception:
            log.exception("Error entregando segmento a STT")

    def _reset_stt_segment(self) -> None:
        self._stt_frames = []
        self._stt_segment_active = False
        self._stt_segment_started_at = 0.0
        self._stt_preroll.clear()

    # ── PyAudio callback (debe ser rápido) ───────────────────────

    def _in_callback(self, in_data, frame_count, time_info, status):
        chunk = self._cfg.chunk

        # ── Preprocesamiento de micrófono (DSP chain) ────────────
        raw = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)

        # 1) Eliminar DC offset (rumble eléctrico del INMP441)
        raw -= np.mean(raw)
        raw_rms = float(np.sqrt(np.mean(raw ** 2)))
        self._record_calibration_sample(raw_rms)

        # 2) AGC — Automatic Gain Control
        #    El VAD decide con RMS pre-AGC para que el ruido de fondo no se
        #    convierta en "voz" solo porque la ganancia lo levantó.
        now_mono = time.monotonic()
        voice_gate_open = self._update_vad_state(raw_rms, now_mono)

        if voice_gate_open:
            target_gain = 3000.0 / max(raw_rms, 1.0)
            target_gain = float(np.clip(target_gain, 1.0, 20.0))

            if target_gain < self._agc_gain:
                alpha = 0.5    # Baja rápido (protege contra clipping)
            else:
                alpha = 0.05   # Sube lento (evita amplificar ruido en pausas)
            self._agc_gain = alpha * target_gain + (1.0 - alpha) * self._agc_gain
        else:
            # Silencio: decaer ganancia gradualmente al baseline
            self._agc_gain = max(self._agc_gain * 0.98, self._cfg.mic_gain)

        raw *= self._agc_gain
        np.clip(raw, -32768, 32767, out=raw)

        processed = raw.astype(np.int16)

        # 3) VAD local con histéresis — detecta voz usando RMS (más
        #    estable que peak). Cuando detecta voz, mantiene el mic
        #    abierto 300ms extra para no cortar finales de palabras.
        #    Solo envía silencio al agente cuando hay silencio real.
        #    El hotword SIEMPRE recibe audio real (no se aplica gate ahí).
        processed_bytes = processed.tobytes()

        # 1) Hotword recibe SIEMPRE audio real (ya amplificado)
        try:
            if processed.shape[0] == chunk:
                if self._hotword_q.full():
                    try:
                        self._hotword_q.get_nowait()
                    except Exception:
                        pass
                self._hotword_q.put_nowait(processed)
        except Exception:
            pass

        # 2) Cola mic -> agente/STT. El sender decide si entrega audio real,
        #    silencio a ElevenLabs, o segmento local a OpenAI.
        try:
            if self._send_q.full():
                try:
                    self._send_q.get_nowait()
                except Exception:
                    pass
            self._send_q.put_nowait((processed_bytes, voice_gate_open))
        except Exception:
            pass

        return (None, pyaudio.paContinue)



# ─────────────────────────────────────────────────────────────────
# HubAudioInterface — adaptador para ElevenLabs
# ─────────────────────────────────────────────────────────────────
class HubAudioInterface(AudioInterface):
    """Implementa la interfaz de audio que espera ElevenLabs Conversation."""

    def __init__(self, hub: AudioHub) -> None:
        self._hub = hub

    def start(self, input_callback: Callable[[bytes], None]) -> None:
        self._hub.attach_input_callback(input_callback)

    def stop(self) -> None:
        self._hub.detach_input_callback()

    def output(self, audio: bytes) -> None:
        self._hub.output(audio)

    def interrupt(self) -> None:
        # NO-OP: El SDK llama esto internamente (correcciones, etc.)
        # pero nosotros NO queremos que corte el audio.
        # Solo el botón físico (app.py → self._hub.interrupt()) puede interrumpir.
        log.debug("SDK solicitó interrupt — ignorado (solo botón físico puede interrumpir)")

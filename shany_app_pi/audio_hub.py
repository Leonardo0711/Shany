"""
audio_hub.py — Capa de audio compartida.

Un solo micrófono y un solo speaker gestionados centralmente.
El hotword siempre recibe audio real; al agente se le envía
silencio mientras él mismo está hablando (anti-eco).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import pyaudio

if TYPE_CHECKING:
    from shany_app_pi.config import ShanyConfig

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

    def __init__(self, config: ShanyConfig) -> None:
        self._cfg = config
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

        # Cola mic → agente
        self._send_q: queue.Queue[bytes] = queue.Queue(
            maxsize=config.send_q_maxsize
        )
        self._input_callback: Optional[Callable[[bytes], None]] = None
        self._cb_lock = threading.Lock()

        # Cola agente → speaker: (generation_id, chunk)
        self._out_q: queue.Queue[tuple[int, bytes]] = queue.Queue(
            maxsize=config.out_q_maxsize
        )
        self._stop = threading.Event()

        # Timestamps de gating
        self._last_output_ts: float = 0.0
        self._force_listen_until: float = 0.0
        self._drop_output_until: float = 0.0

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

    # ── Estado / gating ──────────────────────────────────────────

    def agent_is_speaking(self) -> bool:
        """Devuelve True si el agente está reproduciendo audio."""
        if (time.time() - self._last_output_ts) < 0.25:
            return True
        return not self._out_q.empty()

    def force_listen_window(self, secs: float) -> None:
        """Fuerza que el mic se envíe al agente durante *secs*."""
        self._force_listen_until = time.time() + max(0.0, secs)

    def drop_agent_audio_window(self, secs: float) -> None:
        """Ignora el audio del agente durante *secs*."""
        self._drop_output_until = time.time() + max(0.0, secs)

    def cancel_drop_window(self) -> None:
        """Cancela la ventana de drop (el agente empezó respuesta nueva)."""
        self._drop_output_until = 0.0

    # ── Output (agente → speaker) ────────────────────────────────

    def output(self, audio: bytes) -> None:
        """Encola audio del agente para reproducir."""
        now = time.time()
        self._last_output_ts = now

        # Si ya pasó la ventana de drop, cancelarla definitivamente
        if now >= self._drop_output_until:
            self._drop_output_until = 0.0
        else:
            # Aún en ventana de drop: descartar este chunk
            return

        with self._playback_lock:
            gen = self._playback_generation

        step = self._cfg.output_slice_bytes
        for i in range(0, len(audio), step):
            piece = audio[i : i + step]
            try:
                self._out_q.put_nowait((gen, piece))
            except queue.Full:
                try:
                    self._out_q.get_nowait()
                    self._out_q.put_nowait((gen, piece))
                except Exception:
                    pass

    def interrupt(self) -> None:
        """Corta el playback actual sin cerrar la sesión."""
        with self._playback_lock:
            self._playback_generation += 1

        # Vaciar cola de audio pendiente
        try:
            while True:
                self._out_q.get_nowait()
        except queue.Empty:
            pass

        log.debug("Playback interrumpido")

    # ── Hotword helper ───────────────────────────────────────────

    def hotword_next_frame(self) -> np.ndarray:
        """Bloquea hasta obtener el siguiente frame para el hotword."""
        return self._hotword_q.get()

    # ── Hilos internos ───────────────────────────────────────────

    def _should_send_real_mic(self) -> bool:
        if time.time() < self._force_listen_until:
            return True
        if self.agent_is_speaking():
            return False
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
                gen, audio = self._out_q.get(timeout=0.25)
            except queue.Empty:
                continue
            except Exception:
                continue

            with self._playback_lock:
                current_gen = self._playback_generation

            if gen != current_gen:
                continue

            try:
                if self._out_stream is not None:
                    # ── Pipeline de Salida (Calidad de Audio) ────────
                    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0

                    # 1) Ganancia base
                    samples *= 2.5

                    # 2) Compresor suave (soft-knee) — mantiene volumen alto
                    #    sin el "crackle" del clipping duro. Las muestras fuertes
                    #    se comprimen suavemente en vez de cortarse de golpe.
                    threshold = 0.6
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

                    self._out_stream.write(samples.astype(np.float32).tobytes())
            except Exception:
                pass

    def _sender_loop(self) -> None:
        while not self._stop.is_set():
            try:
                mic_bytes = self._send_q.get(timeout=0.25)
            except queue.Empty:
                continue

            with self._cb_lock:
                cb = self._input_callback

            if cb is None:
                continue

            if self._should_send_real_mic():
                cb(mic_bytes)
            else:
                cb(b"\x00" * len(mic_bytes))

    # ── PyAudio callback (debe ser rápido) ───────────────────────

    def _in_callback(self, in_data, frame_count, time_info, status):
        chunk = self._cfg.chunk

        # ── Preprocesamiento de micrófono (DSP chain) ────────────
        raw = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)

        # 1) Eliminar DC offset (rumble eléctrico del INMP441)
        raw -= np.mean(raw)

        # 2) Ganancia digital 5x — extiende el rango de captación
        raw *= 5.0
        np.clip(raw, -32768, 32767, out=raw)

        processed = raw.astype(np.int16)

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

        # 2) Cola mic → agente (audio amplificado)
        try:
            if self._send_q.full():
                try:
                    self._send_q.get_nowait()
                except Exception:
                    pass
            self._send_q.put_nowait(processed_bytes)
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
        self._hub.interrupt()

"""
elevenlabs_stt.py - Transcripcion por turnos con ElevenLabs Scribe.

Recibe segmentos PCM 16 kHz mono int16 desde el VAD local y los envia a
Scribe v2. El texto final se entrega al agente conversacional mediante
send_user_message.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
import http.client
from typing import Callable, Optional

from shany_app_pi.config import ShanyConfig

log = logging.getLogger(__name__)


class ElevenLabsTranscriber:
    """Worker liviano para transcribir frases completas con Scribe."""

    _HOST = "api.elevenlabs.io"
    _PATH = "/v1/speech-to-text"
    _EMPTY_TEXTS = {"", ".", "..", "...", "…", "[silencio]", "(silencio)"}

    def __init__(self, config: ShanyConfig, on_transcript: Callable[[str], None]) -> None:
        self._cfg = config
        self._on_transcript = on_transcript
        self._queue: queue.Queue[tuple[int, bytes, int, float]] = queue.Queue(
            maxsize=config.elevenlabs_stt_queue_size
        )
        self._generation = 0
        self._generation_lock = threading.Lock()
        self._conn: Optional[http.client.HTTPSConnection] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="elevenlabs-stt"
        )
        self._thread.start()
        log.info("ElevenLabs STT iniciado (model=%s)", self._cfg.elevenlabs_stt_model)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close_connection()
        log.info("ElevenLabs STT apagado")

    def clear_pending(self) -> None:
        """Descarta segmentos pendientes y resultados de la generación anterior."""
        with self._generation_lock:
            self._generation += 1
            generation = self._generation
        dropped = 0
        try:
            while True:
                self._queue.get_nowait()
                dropped += 1
        except queue.Empty:
            pass
        if dropped:
            log.info("STT cola limpiada: %d segmento(s) descartado(s)", dropped)
        log.debug("STT generación activa=%d", generation)

    def submit(self, pcm16: bytes, sample_rate: int) -> bool:
        duration = len(pcm16) / float(sample_rate * 2)
        if duration < self._cfg.elevenlabs_stt_min_audio_sec:
            log.info("STT omitido: segmento muy corto (%.2fs)", duration)
            return False
        if duration > self._cfg.elevenlabs_stt_max_audio_sec:
            max_bytes = int(self._cfg.elevenlabs_stt_max_audio_sec * sample_rate * 2)
            pcm16 = pcm16[:max_bytes]
            duration = self._cfg.elevenlabs_stt_max_audio_sec
            log.info("STT recortado a %.1fs", duration)

        with self._generation_lock:
            generation = self._generation

        item = (generation, pcm16, sample_rate, duration)
        try:
            self._queue.put_nowait(item)
            log.info("STT encolado: %.2fs bytes=%d", duration, len(pcm16))
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(item)
                log.warning("STT cola llena: se descarto el segmento anterior")
                return True
            except queue.Full:
                log.warning("STT cola llena: segmento descartado")
                return False

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                generation, pcm16, sample_rate, duration = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            started = time.time()
            try:
                text = self._transcribe(pcm16)
                elapsed = time.time() - started
                with self._generation_lock:
                    current_generation = self._generation
                if generation != current_generation:
                    log.info("STT resultado antiguo omitido (%.2fs)", elapsed)
                    continue
                cleaned = self._clean_text(text)
                if not cleaned:
                    log.info("STT vacio/ruido omitido (%.2fs)", elapsed)
                    continue
                log.info("STT listo en %.2fs audio=%.2fs text=%s", elapsed, duration, cleaned)
                self._on_transcript(cleaned)
            except Exception as exc:
                log.warning("STT fallo: %s", exc)

    def _transcribe(self, pcm16: bytes) -> str:
        fields = {
            "model_id": self._cfg.elevenlabs_stt_model,
            "file_format": self._cfg.elevenlabs_stt_file_format,
            "language_code": self._cfg.elevenlabs_stt_language,
            "tag_audio_events": str(self._cfg.elevenlabs_stt_tag_audio_events).lower(),
            "diarize": str(self._cfg.elevenlabs_stt_diarize).lower(),
            "timestamps_granularity": "none",
        }
        body, content_type = self._multipart_body(fields, pcm16)
        payload = self._post_json(body, content_type)

        return str(payload.get("text", ""))

    def _post_json(self, body: bytes, content_type: str) -> dict:
        headers = {
            "xi-api-key": self._cfg.stt_api_key,
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }

        last_error: Optional[BaseException] = None
        for attempt in range(2):
            try:
                conn = self._connection()
                conn.request("POST", self._PATH, body=body, headers=headers)
                resp = conn.getresponse()
                raw = resp.read().decode("utf-8", errors="replace")
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}: {raw[:300]}")
                return json.loads(raw)
            except (OSError, http.client.HTTPException, RuntimeError) as exc:
                last_error = exc
                self._close_connection()
                if isinstance(exc, RuntimeError) or attempt == 1:
                    raise
                log.debug("Reintentando STT tras reconectar: %s", exc)

        raise RuntimeError(str(last_error))

    def _connection(self) -> http.client.HTTPSConnection:
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(
                self._HOST,
                timeout=self._cfg.elevenlabs_stt_timeout_sec,
            )
        return self._conn

    def _close_connection(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = None

    @staticmethod
    def _multipart_body(fields: dict[str, str], pcm16: bytes) -> tuple[bytes, str]:
        boundary = f"shany-{uuid.uuid4().hex}"
        chunks: list[bytes] = []

        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    'Content-Disposition: form-data; name="file"; '
                    'filename="shany_turn.pcm"\r\n'
                ).encode("ascii"),
                b"Content-Type: application/octet-stream\r\n\r\n",
                pcm16,
                b"\r\n",
                f"--{boundary}--\r\n".encode("ascii"),
            ]
        )
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    @classmethod
    def _clean_text(cls, text: str) -> str:
        cleaned = " ".join(text.replace("\n", " ").split()).strip()
        if cleaned.lower() in cls._EMPTY_TEXTS:
            return ""
        return cleaned

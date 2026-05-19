"""Streaming TTS de ElevenLabs para el motor realtime de Shany."""

from __future__ import annotations

import http.client
import json
import logging
import queue
import threading
from typing import Callable, Optional

from shany_app_pi.config import ShanyConfig

log = logging.getLogger(__name__)


class ElevenLabsTTSStreamer:
    """Convierte texto en audio PCM y lo entrega al AudioHub."""

    _HOST = "api.elevenlabs.io"

    def __init__(
        self,
        config: ShanyConfig,
        on_audio: Callable[[bytes], None],
        on_busy_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._cfg = config
        self._on_audio = on_audio
        self._on_busy_change = on_busy_change
        self._queue: queue.Queue[tuple[int, str]] = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._generation = 0
        self._generation_lock = threading.Lock()
        self._busy = False
        self._busy_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="elevenlabs-tts")
        self._thread.start()
        log.info("ElevenLabs TTS iniciado (model=%s)", self._cfg.elevenlabs_tts_model)

    def shutdown(self) -> None:
        self._stop.set()
        self.cancel()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        log.info("ElevenLabs TTS apagado")

    def cancel(self) -> None:
        with self._generation_lock:
            self._generation += 1
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._set_busy(False)

    def speak(self, text: str) -> bool:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return False
        with self._generation_lock:
            generation = self._generation
        try:
            self._queue.put_nowait((generation, cleaned))
            self._set_busy(True)
            return True
        except queue.Full:
            log.warning("TTS cola llena; descartando segmento")
            return False

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                generation, text = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._stream_text(generation, text)
            except Exception as exc:
                log.warning("TTS fallo: %s", exc)
            finally:
                if self._queue.empty():
                    self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        with self._busy_lock:
            if self._busy == busy:
                return
            self._busy = busy
        if self._on_busy_change:
            try:
                self._on_busy_change(busy)
            except Exception:
                log.exception("Callback TTS busy fallo")

    def _stream_text(self, generation: int, text: str) -> None:
        path = (
            f"/v1/text-to-speech/{self._cfg.elevenlabs_tts_voice_id}/stream"
            f"?output_format={self._cfg.elevenlabs_tts_output_format}"
            f"&optimize_streaming_latency={self._cfg.elevenlabs_tts_latency}"
        )
        body = json.dumps(
            {
                "text": text,
                "model_id": self._cfg.elevenlabs_tts_model,
                "voice_settings": {
                    "stability": 0.55,
                    "similarity_boost": 0.75,
                    "style": 0.2,
                    "use_speaker_boost": True,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "xi-api-key": self._cfg.elevenlabs_tts_api_key,
            "Content-Type": "application/json",
            "Accept": "application/octet-stream",
            "Content-Length": str(len(body)),
        }

        conn = http.client.HTTPSConnection(self._HOST, timeout=20.0)
        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            if resp.status >= 400:
                raw = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {resp.status}: {raw[:300]}")

            while not self._stop.is_set():
                with self._generation_lock:
                    if generation != self._generation:
                        return
                chunk = resp.read(4096)
                if not chunk:
                    return
                self._on_audio(chunk)
        finally:
            try:
                conn.close()
            except Exception:
                pass

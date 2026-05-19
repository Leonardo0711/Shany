"""Cliente OpenAI Realtime para escuchar y generar texto de Shany."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from typing import Callable, Optional

import numpy as np
import websockets

from shany_app_pi.config import ShanyConfig
from shany_app_pi.shany_prompt import SHANY_REALTIME_PROMPT

log = logging.getLogger(__name__)


class OpenAIRealtimeManager:
    """WebSocket realtime: audio in, text deltas out."""

    def __init__(
        self,
        config: ShanyConfig,
        *,
        on_text_delta: Callable[[str], None],
        on_response_started: Callable[[], None],
        on_response_done: Callable[[], None],
        on_user_transcript: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._cfg = config
        self._on_text_delta = on_text_delta
        self._on_response_started = on_response_started
        self._on_response_done = on_response_done
        self._on_user_transcript = on_user_transcript

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._audio_q: Optional[asyncio.Queue[bytes]] = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._ws = None

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._connected.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True, name="openai-realtime")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._connected.clear()
        if self._loop:
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def submit_audio(self, pcm16_16k: bytes) -> None:
        if not self._loop or not self._audio_q or not self._connected.is_set():
            return

        def _put() -> None:
            if self._audio_q is None:
                return
            try:
                self._audio_q.put_nowait(pcm16_16k)
            except asyncio.QueueFull:
                try:
                    self._audio_q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self._audio_q.put_nowait(pcm16_16k)
                except asyncio.QueueFull:
                    pass

        self._loop.call_soon_threadsafe(_put)

    def cancel_response(self) -> None:
        if not self._loop or not self._ws:
            return
        asyncio.run_coroutine_threadsafe(
            self._send({"type": "response.cancel"}),
            self._loop,
        )

    def _run_thread(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._connected.clear()
            self._loop.close()
            self._loop = None

    async def _main(self) -> None:
        self._audio_q = asyncio.Queue(maxsize=3)
        url = f"{self._cfg.openai_realtime_url}?model={self._cfg.openai_realtime_model}"
        headers = {
            "Authorization": f"Bearer {self._cfg.openai_api_key}",
        }

        try:
            try:
                ws_cm = websockets.connect(
                    url,
                    additional_headers=headers,
                    max_size=16 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20,
                )
            except TypeError:
                ws_cm = websockets.connect(
                    url,
                    extra_headers=headers,
                    max_size=16 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20,
                )

            async with ws_cm as ws:
                self._ws = ws
                await self._configure_session()
                self._connected.set()
                log.info("OpenAI Realtime conectado (model=%s)", self._cfg.openai_realtime_model)
                await asyncio.gather(self._send_audio_loop(), self._receive_loop())
        except Exception as exc:
            log.warning("OpenAI Realtime desconectado: %s", exc)
        finally:
            self._connected.clear()
            self._ws = None

    async def _send(self, payload: dict) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(payload))

    async def _configure_session(self) -> None:
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": SHANY_REALTIME_PROMPT,
                    "output_modalities": ["text"],
                    "audio": {
                        "input": {
                            "format": {
                                "type": "audio/pcm",
                                "rate": self._cfg.openai_realtime_input_rate,
                            },
                            "noise_reduction": {
                                "type": "near_field",
                            },
                            "transcription": {
                                "model": "gpt-4o-mini-transcribe",
                                "language": "es",
                            },
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": self._cfg.openai_realtime_vad_threshold,
                                "prefix_padding_ms": self._cfg.openai_realtime_prefix_padding_ms,
                                "silence_duration_ms": self._cfg.openai_realtime_silence_duration_ms,
                                "create_response": True,
                                "interrupt_response": False,
                            },
                        },
                    },
                    "max_output_tokens": 220,
                },
            }
        )

    async def _send_audio_loop(self) -> None:
        assert self._audio_q is not None
        while not self._stop.is_set():
            pcm16_16k = await self._audio_q.get()
            pcm16_24k = self._resample_pcm16(pcm16_16k, self._cfg.sample_rate, self._cfg.openai_realtime_input_rate)
            await self._send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm16_24k).decode("ascii"),
                }
            )

    async def _receive_loop(self) -> None:
        while not self._stop.is_set() and self._ws is not None:
            raw = await self._ws.recv()
            event = json.loads(raw)
            etype = event.get("type", "")

            if etype in {"response.created", "response.output_item.added"}:
                self._on_response_started()
            elif etype in {"response.text.delta", "response.output_text.delta"}:
                delta = event.get("delta", "")
                if delta:
                    self._on_text_delta(delta)
            elif etype in {"response.text.done", "response.output_text.done"}:
                text = event.get("text", "")
                if text:
                    log.info("OpenAI text done: %s", text)
            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "").strip()
                if transcript:
                    log.info("User(OpenAI): %s", transcript)
                    if self._on_user_transcript:
                        self._on_user_transcript(transcript)
            elif etype == "input_audio_buffer.speech_started":
                log.info("OpenAI VAD: speech_started")
            elif etype == "input_audio_buffer.speech_stopped":
                log.info("OpenAI VAD: speech_stopped")
            elif etype == "session.updated":
                log.info("OpenAI Realtime session configurada")
            elif etype == "response.done":
                self._on_response_done()
            elif etype == "error":
                log.warning("OpenAI Realtime error: %s", event)

    @staticmethod
    def _resample_pcm16(pcm16: bytes, src_rate: int, dst_rate: int) -> bytes:
        if src_rate == dst_rate:
            return pcm16
        samples = np.frombuffer(pcm16, dtype=np.int16)
        if samples.size == 0:
            return pcm16
        src_x = np.arange(samples.size, dtype=np.float32)
        dst_size = max(1, int(samples.size * dst_rate / src_rate))
        dst_x = np.linspace(0, samples.size - 1, dst_size, dtype=np.float32)
        resampled = np.interp(dst_x, src_x, samples.astype(np.float32))
        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()

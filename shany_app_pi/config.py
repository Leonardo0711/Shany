"""
config.py — Configuración centralizada de Shany.

Lee credenciales desde .env y expone todos los parámetros como un
dataclass inmutable.  Nada en este módulo depende de hardware ni de
librerías externas pesadas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ── Directorios del Proyecto ─────────────────────────────────────
_PACKAGE_DIR = Path(__file__).resolve().parent
# shany_Raspberry es el padre de shany_app_pi
_PROJECT_DIR = _PACKAGE_DIR.parent 


def _load_dotenv(path: Path) -> None:
    """Carga un .env simple (KEY=VALUE) en os.environ."""
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key:
                os.environ.setdefault(key, value)


# Cargar .env al importar este módulo (buscando en el nivel superior si no está aquí)
_load_dotenv(_PACKAGE_DIR / ".env")


@dataclass(frozen=True)
class ShanyConfig:
    """Parámetros de la aplicación Shany optimizados para RPi Zero 2W."""

    # ── Credenciales (leídas del .env) ───────────────────────────
    agent_id: str = field(
        default_factory=lambda: os.environ.get(
            "ELEVENLABS_AGENT_ID", ""
        )
    )
    api_key: str = field(
        default_factory=lambda: os.environ.get(
            "ELEVENLABS_API_KEY", ""
        )
    )
    stt_api_key: str = field(
        default_factory=lambda: os.environ.get(
            "ELEVENLABS_STT_API_KEY", os.environ.get("ELEVENLABS_API_KEY", "")
        )
    )
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    elevenlabs_tts_api_key: str = field(
        default_factory=lambda: os.environ.get(
            "ELEVENLABS_TTS_API_KEY", os.environ.get("ELEVENLABS_API_KEY", "")
        )
    )
    elevenlabs_tts_voice_id: str = field(
        default_factory=lambda: os.environ.get("ELEVENLABS_TTS_VOICE_ID", "")
    )
    # ── Rutas a archivos de referencia de hotword ────────────────
    # Se busca la carpeta 'hotword_refs' al mismo nivel que 'shany_app_pi'
    ref_hola: Path = field(
        default_factory=lambda: _PROJECT_DIR / "hotword_refs" / "hola_shany_ref.json"
    )
    ref_shany: Path = field(
        default_factory=lambda: _PROJECT_DIR / "hotword_refs" / "shany_ref.json"
    )

    # ── Pines de Hardware ────────────────────────────────────────
    button_pin: int = 23  # GPIO 23 (Pin físico 16)

    # ── Audio / Hotword stream ───────────────────────────────────
    sample_rate: int = 16_000
    sliding_window_secs: float = 0.04
    window_length_secs: float = 1.50

    # ── Hotword thresholds ───────────────────────────────────────
    wake_threshold: float = 0.70
    wake_relaxation: float = 2.0
    interrupt_threshold: float = 0.63
    interrupt_relaxation: float = 0.8

    # ── Interrupción / gating ────────────────────────────────────
    force_listen_secs: float = 3.0
    drop_agent_audio_secs: float = 1.0
    wake_to_interrupt_block_sec: float = 1.5

    # ── Timeout de sesión ────────────────────────────────────────
    inactivity_timeout_sec: float = 300.0

    # ── Audio Hub internos (Optimizados para Pi Zero 2W) ─────────
    output_frames_per_buffer: int = 4096  # Aumentado para evitar underruns
    output_slice_bytes: int = 640  # 20 ms @ 16 kHz mono int16
    hotword_q_maxsize: int = 100
    send_q_maxsize: int = 400
    out_q_maxsize: int = 1000

    # ── Audio DSP / Tuning ───────────────────────────────────────
    mic_gain: float = 5.0
    mic_noise_threshold: int = 500  # Compatibilidad: umbral antiguo post-AGC.
    output_gain: float = 0.5  # 20% del volumen original
    output_comp_threshold: float = 0.6
    output_soft_silence_sec: float = 0.55
    output_final_silence_sec: float = 0.95
    agent_turn_max_wait_sec: float = 25.0
    elevenlabs_silence_keepalive_sec: float = 2.0
    elevenlabs_silence_burst_sec: float = 1.2

    # ── VAD inteligente / calibración de ambiente ───────────────
    runtime_calibration_file: Path = field(
        default_factory=lambda: _PACKAGE_DIR / "runtime_calibration.json"
    )
    vad_noise_threshold: int = 65  # RMS pre-AGC usado si aún no hay calibración.
    vad_min_threshold: int = 55
    vad_max_threshold: int = 1800
    vad_close_ratio: float = 0.65
    vad_start_frames: int = 2
    vad_stop_frames: int = 3
    vad_hold_sec: float = 0.18
    vad_calibration_secs: float = 4.0
    vad_calibration_percentile: float = 95.0
    vad_calibration_multiplier: float = 1.8

    # ── STT por turno con ElevenLabs Scribe ──────────────────────
    turn_stt_enabled: bool = field(
        default_factory=lambda: os.environ.get(
            "SHANY_TURN_STT_ENABLED", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
    )
    elevenlabs_stt_model: str = field(
        default_factory=lambda: os.environ.get(
            "ELEVENLABS_STT_MODEL", "scribe_v2"
        )
    )
    elevenlabs_stt_language: str = field(
        default_factory=lambda: os.environ.get("ELEVENLABS_STT_LANGUAGE", "spa")
    )
    elevenlabs_stt_timeout_sec: float = 10.0
    elevenlabs_stt_min_audio_sec: float = 0.45
    elevenlabs_stt_max_audio_sec: float = 6.0
    elevenlabs_stt_queue_size: int = 2
    turn_stt_preroll_frames: int = 2
    elevenlabs_stt_file_format: str = "pcm_s16le_16"
    elevenlabs_stt_tag_audio_events: bool = False
    elevenlabs_stt_diarize: bool = False
    elevenlabs_audio_input_with_turn_stt: bool = False
    realtime_audio_passthrough: bool = field(
        default_factory=lambda: os.environ.get(
            "SHANY_REALTIME_AUDIO_PASSTHROUGH", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
    )

    # ── OpenAI Realtime + ElevenLabs TTS (motor v2 experimental) ──
    openai_realtime_model: str = field(
        default_factory=lambda: os.environ.get(
            "OPENAI_REALTIME_MODEL", "gpt-realtime"
        )
    )
    openai_realtime_url: str = "wss://api.openai.com/v1/realtime"
    openai_realtime_input_rate: int = 24_000
    openai_realtime_vad_threshold: float = 0.50
    openai_realtime_prefix_padding_ms: int = 180
    openai_realtime_silence_duration_ms: int = 450
    elevenlabs_tts_model: str = field(
        default_factory=lambda: os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")
    )
    elevenlabs_tts_output_format: str = field(
        default_factory=lambda: os.environ.get("ELEVENLABS_TTS_OUTPUT_FORMAT", "pcm_16000")
    )
    elevenlabs_tts_latency: int = 3
    elevenlabs_tts_flush_chars: int = 110

    # ── Propiedades derivadas ────────────────────────────────────
    @property
    def chunk(self) -> int:
        """Samples por frame del micrófono."""
        return int(self.sliding_window_secs * self.sample_rate)

    def validate(self) -> None:
        """Lanza ValueError si la config es inválida."""
        if not self.agent_id:
            raise ValueError(
                "ELEVENLABS_AGENT_ID no está definido. "
                "Revisa el archivo .env dentro de la carpeta de la app."
            )
        if not self.api_key:
            raise ValueError(
                "ELEVENLABS_API_KEY no está definido. "
                "Revisa el archivo .env dentro de la carpeta de la app."
            )
        if self.turn_stt_enabled and not self.stt_api_key:
            raise ValueError(
                "ELEVENLABS_STT_API_KEY no está definido y SHANY_TURN_STT_ENABLED está activo. "
                "Revisa el archivo .env dentro de la carpeta de la app."
            )
        # Nota: La validación de archivos se hará al iniciar en la Pi

    def validate_realtime(self) -> None:
        """Valida el motor v2: OpenAI Realtime + ElevenLabs TTS."""
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY no está definido en .env")
        if not self.elevenlabs_tts_api_key:
            raise ValueError("ELEVENLABS_TTS_API_KEY o ELEVENLABS_API_KEY no está definido en .env")
        if not self.elevenlabs_tts_voice_id:
            raise ValueError("ELEVENLABS_TTS_VOICE_ID no está definido en .env")

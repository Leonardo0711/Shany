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
    sliding_window_secs: float = 0.20
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
    mic_noise_threshold: int = 500  # RMS post-AGC. Con AGC, voz ~2000-3000, ruido ~200-400
    output_gain: float = 2.5
    output_comp_threshold: float = 0.6

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
        # Nota: La validación de archivos se hará al iniciar en la Pi

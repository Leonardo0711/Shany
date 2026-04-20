"""
hardware_button.py — Gestión del botón físico mediante GPIO.

Permite actuar como respaldo físico para las interacciones con Shany:
- Click simple: Despierta a Shany (equivalente a "Hola Shany").
- Doble click: Apaga a Shany / Cierra sesión.
- Hold (Mantener presionado): Interrumpe y fuerza a escuchar (equivalente a "Shany").
"""

import logging
import threading
import time
from typing import Callable, Optional
from gpiozero import Button

log = logging.getLogger(__name__)

class SmartButton:
    def __init__(
        self,
        pin: int,
        on_single_click: Callable[[], None],
        on_double_click: Callable[[], None],
        on_hold: Callable[[], None],
        hold_time: float = 1.0,
        double_click_threshold: float = 0.4
    ):
        """
        Inicializa un botón inteligente.
        :param pin: GPIO pin (ej. 23).
        :param on_single_click: Callback para click simple.
        :param on_double_click: Callback para doble click.
        :param on_hold: Callback para mantener presionado.
        :param hold_time: Tiempo en segundos para considerar "Hold".
        :param double_click_threshold: Umbral máximo entre clicks para doble click.
        """
        self.on_single_click = on_single_click
        self.on_double_click = on_double_click
        self.on_hold = on_hold
        
        self.double_click_threshold = double_click_threshold

        self._last_click_time = 0.0
        self._was_held = False
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        try:
            # gpiozero maneja la resistencia PULL-UP internamente por defecto
            self.button = Button(pin, hold_time=hold_time)
            self.button.when_pressed = self._pressed
            self.button.when_released = self._released
            self.button.when_held = self._held
            log.info("SmartButton inicializado en GPIO %d", pin)
        except Exception as e:
            log.error("Error al inicializar el botón GPIO: %s", e)

    def _pressed(self) -> None:
        with self._lock:
            self._was_held = False

    def _held(self) -> None:
        with self._lock:
            self._was_held = True
            log.debug("SmartButton: Emitiendo Hold")
        self.on_hold()

    def _trigger_single(self) -> None:
        with self._lock:
            self._timer = None
        log.debug("SmartButton: Emitiendo Single Click")
        self.on_single_click()

    def _released(self) -> None:
        with self._lock:
            if self._was_held:
                return
            
            now = time.time()
            if now - self._last_click_time < self.double_click_threshold:
                # Es un doble click
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                self._last_click_time = 0.0  # Reiniciar para evitar triples
                log.debug("SmartButton: Emitiendo Double Click")
                # Llamar fuera del lock es opcional, pero aquí está bien
                threading.Thread(target=self.on_double_click, daemon=True).start()
            else:
                # Primer click, esperar a ver si es simple o el primero de un doble
                self._last_click_time = now
                self._timer = threading.Timer(
                    self.double_click_threshold, self._trigger_single
                )
                self._timer.start()

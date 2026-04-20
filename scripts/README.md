# Herramientas de Automatización en Python para Shany

He migrado los scripts a Python para que yo (Antigravity) pueda interactuar con la Raspberry Pi de forma más directa y para que cualquier sesión futura tenga estas herramientas listas.

## Archivos

1.  **`pi_config.py`**: Configuración central (Credenciales y helpers).
2.  **`pi_check.py`**: Muestra el estado del sistema (Memoria, Disco, Uptime).
    *   *Uso:* `python pi_check.py`
3.  **`pi_deploy.py`**: Sube archivos o carpetas a la Pi.
    *   *Uso:* `python pi_deploy.py "ruta/a/mi/archivo"`

## Requisitos
*   Python 3.x instalado en Windows.
*   PuTTY (`plink` y `pscp`) disponible en el PATH.

# Configuración de acceso para la Raspberry Pi
import os

PI_CONFIG = {
    "user": "ietsi",
    "pass": "Essalud2026#",
    "host": "shany.local",
    "remote_path": "/home/ietsi"
}

def get_ssh_base_cmd():
    """Retorna la base del comando plink con credenciales."""
    return ["plink", "-pw", PI_CONFIG["pass"], f"{PI_CONFIG['user']}@{PI_CONFIG['host']}"]

def get_pscp_base_cmd(recursive=False):
    """Retorna la base del comando pscp con credenciales."""
    cmd = ["pscp", "-pw", PI_CONFIG["pass"]]
    if recursive:
        cmd.append("-r")
    return cmd

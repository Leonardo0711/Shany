#!/bin/bash
# ============================================================
# install_service.sh — Instala Shany como servicio del sistema
#
# Ejecutar DESDE la Raspberry Pi con:
#   sudo bash /home/ietsi/shany_app_pi/install_service.sh
# ============================================================

set -e

SERVICE_NAME="shany"
SERVICE_FILE="/home/ietsi/shany_app_pi/shany.service"
SYSTEMD_DIR="/etc/systemd/system"

echo "═══════════════════════════════════════════════════"
echo "  Instalador del servicio Shany"
echo "═══════════════════════════════════════════════════"

# 1) Verificar que el archivo existe
if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: No se encontró $SERVICE_FILE"
    exit 1
fi

# 2) Detener servicio si ya existe
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "[1/5] Deteniendo servicio existente..."
    systemctl stop "$SERVICE_NAME"
else
    echo "[1/5] No hay servicio previo corriendo."
fi

# 3) Copiar el archivo de servicio
echo "[2/5] Copiando shany.service a systemd..."
cp "$SERVICE_FILE" "$SYSTEMD_DIR/${SERVICE_NAME}.service"

# 4) Recargar systemd
echo "[3/5] Recargando systemd..."
systemctl daemon-reload

# 5) Habilitar para arranque automático
echo "[4/5] Habilitando arranque automático..."
systemctl enable "$SERVICE_NAME"

# 6) Iniciar ahora
echo "[5/5] Iniciando Shany..."
systemctl start "$SERVICE_NAME"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Servicio instalado correctamente"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Comandos útiles:"
echo "  Estado:     sudo systemctl status shany"
echo "  Logs:       sudo journalctl -u shany -f"
echo "  Reiniciar:  sudo systemctl restart shany"
echo "  Detener:    sudo systemctl stop shany"
echo "  Desactivar: sudo systemctl disable shany"
echo ""

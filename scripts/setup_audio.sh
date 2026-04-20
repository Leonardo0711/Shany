#!/bin/bash
# Script para configurar audio I2S en Raspberry Pi
set -e

CONFIG_FILE="/boot/firmware/config.txt"
PASS="Essalud2026#"

echo "Habilitando I2S en $CONFIG_FILE..."
echo "$PASS" | sudo -S sed -i 's/#dtparam=i2s=on/dtparam=i2s=on/' "$CONFIG_FILE"

echo "Agregando overlay googlevoicehat-soundcard..."
if ! grep -q "googlevoicehat-soundcard" "$CONFIG_FILE"; then
    echo "$PASS" | sudo -S bash -c "echo 'dtoverlay=googlevoicehat-soundcard' >> $CONFIG_FILE"
fi

echo "Actualizando sistema e instalando dependencias de audio..."
echo "$PASS" | sudo -S apt-get update
echo "$PASS" | sudo -S apt-get install -y portaudio19-dev libasound2-dev alsa-utils

echo "Configuración completada con éxito. Listo para reiniciar."

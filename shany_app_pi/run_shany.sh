#!/bin/bash
# run_shany.sh - Lanzador de Shany optimizado para RPi Zero 2W

# Limpiar posibles procesos previos
pkill -f shany_app_pi || true

# Configurar el path para incluir la raíz del proyecto
export PYTHONPATH=$PYTHONPATH:/home/ietsi

# Ejecutar el módulo shany_app_pi usando el venv
echo "Iniciando Shany (Raspberry Pi Edition)..."
/home/ietsi/shany_env/bin/python3 -m shany_app_pi

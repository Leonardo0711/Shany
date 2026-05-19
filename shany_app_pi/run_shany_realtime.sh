#!/bin/bash
# run_shany_realtime.sh - Lanzador experimental OpenAI Realtime + ElevenLabs TTS

pkill -f '[s]hany_app_pi.realtime_main' || true

export PYTHONPATH=$PYTHONPATH:/home/ietsi/shany_realtime

echo "Iniciando Shany Realtime (OpenAI + ElevenLabs TTS)..."
/home/ietsi/shany_env/bin/python3 -m shany_app_pi.realtime_main

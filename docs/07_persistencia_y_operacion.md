# Paso 7: Mantenimiento, Variables y Arranque Automático

Para asegurar que Shany opere como un verdadero dispositivo "headless" (sin pantalla ni teclado), debe conectarse sola y saber recuperarse de caídas o cortes de luz.

## 1. El Archivo de Variables (`.env`)

Toda aplicación de IA requiere credenciales. En esta Raspberry, existe un archivo oculto `.env` ubicado en `/home/ietsi/shany_app_pi/.env`. **Este archivo nunca se sube a GitHub por seguridad.**

Si necesitas configurar el dispositivo desde cero, debes crear este archivo con el siguiente contenido:

```env
ELEVENLABS_API_KEY=sk-tu-clave-secreta-aqui
ELEVENLABS_AGENT_ID=tu-agent-id-aqui
```

*Recordatorio:* El entorno de Shany requiere que estas claves correspondan a ElevenLabs con un agente Conversacional activo.

## 2. Ejecución Manual y Monitoreo

Si deseas arrancar Shany temporalmente en el terminal SSH, ejecuta:
```bash
sh /home/ietsi/run_shany.sh
```

### Herramientas de Monitoreo (`top` y `htop`)
Para verificar que el filtrado digital o el "hotword engine" no estén ahorcando la Raspberry:
- Correr `top` (o instalar `htop`).
- PyAudio generará una carga base (~20% - 30%) incluso en silencio debido a la evaluación constante mediante `numpy` en frames de 3200 de longitud y el control del motor neuronal.
- Si notas que se acerca al 80% o se detiene, verifica el estado del `swap`.

## 3. Auto-arranque Permanente (Systemd)

Para que el robot viva tan pronto lo enchufes a la pared, debes volverlo un servicio oficial del sistema Linux.

### Crear el servicio:
Ejecuta `sudo nano /etc/systemd/system/shany.service` y pega esto:

```ini
[Unit]
Description=Shany AI Conversational Assistant
After=network.target sound.target

[Service]
Type=simple
User=ietsi
WorkingDirectory=/home/ietsi
ExecStart=/bin/bash /home/ietsi/run_shany.sh
Restart=on-failure
RestartSec=5
# Esto evita que inicie antes de que el micrófono ALSA esté listo
ExecStartPre=/bin/sleep 10 

[Install]
WantedBy=multi-user.target
```

### Habilitar y controlar Shany:
Una vez guardado el archivo, ejecuta estos comandos para encenderlo:

```bash
# Recargar el sistema de servicios
sudo systemctl daemon-reload

# Habilitar para que inicie en cada reinicio de la Raspberry
sudo systemctl enable shany.service

# Iniciar ahora mismo sin necesidad de reiniciar la Pi
sudo systemctl start shany.service
```

### Revisar cómo piensa Shany (Logs en Vivo):
Dado que ahora corre de fondo, si quieres ver qué está haciendo (*si detectó un tap en el botón, si ElevenLabs contestó, etc.*), solo debes invocar sus logs de sistema:

```bash
# Ver los logs en tiempo real (Ctrl+C para salir)
sudo journalctl -u shany.service -f
```

---
*Fin Documentación de Arquitectura de Raspberry Pi - Shany AI*

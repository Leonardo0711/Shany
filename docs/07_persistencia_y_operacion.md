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

### Archivo de servicio (`shany.service`):

El archivo ya viene incluido dentro de `shany_app_pi/shany.service` con la configuración optimizada:

```ini
[Unit]
Description=Shany AI Assistant (Raspberry Pi)
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=ietsi
Group=ietsi
WorkingDirectory=/home/ietsi
Environment=PYTHONPATH=/home/ietsi
Environment=HOME=/home/ietsi
ExecStart=/home/ietsi/shany_env/bin/python3 -m shany_app_pi
ExecStartPre=/usr/bin/pkill -f shany_app_pi || /bin/true
Restart=on-failure
RestartSec=5
TimeoutStartSec=120
StandardOutput=journal
StandardError=journal
SyslogIdentifier=shany

[Install]
WantedBy=multi-user.target
```

**Mejoras respecto a la versión anterior:**
- Usa `network-online.target` en vez de `network.target` → espera a que la red esté realmente conectada (necesario para ElevenLabs API).
- Ejecuta Python directamente sin pasar por el shell script → menos overhead.
- `TimeoutStartSec=120` → da 2 minutos al modelo de hotword para cargar sin que systemd lo mate.
- `ExecStartPre` mata procesos previos automáticamente.

### Instalación automática:

Se incluye un script de instalación que automatiza todo el proceso:

```bash
# Conectar vía SSH
ssh ietsi@shany.local

# Ejecutar el instalador (requiere sudo)
sudo bash /home/ietsi/shany_app_pi/install_service.sh
```

El script realiza:
1. Detiene el servicio anterior (si existía).
2. Copia `shany.service` a `/etc/systemd/system/`.
3. Recarga systemd.
4. Habilita el arranque automático.
5. Inicia Shany inmediatamente.

### Señal `system:ready` al ESP32:

Al iniciar, Shany envía un mensaje JSON al ESP32 por UART cuando está **realmente lista** para escuchar. Esto ocurre **después** de:

1. ✅ AudioHub inicializado (micrófono + speaker).
2. ✅ HotwordEngine cargado (modelo neuronal Resnet50).
3. ✅ Monitor de inactividad activo.

Solo entonces se envía:
```json
{"type":"system","state":"ready","seq":1,"sent_ms":12345}
```

El ESP32 recibe este mensaje y hace parpadear el **LED RGB en cian** durante 1.6 segundos, indicando al usuario que ya puede decir "Hola Shany". Antes de recibir este mensaje, el LED permanece apagado.

### Habilitar y controlar Shany (referencia rápida):

```bash
# Estado del servicio
sudo systemctl status shany

# Logs en tiempo real (Ctrl+C para salir)
sudo journalctl -u shany -f

# Reiniciar
sudo systemctl restart shany

# Detener
sudo systemctl stop shany

# Desactivar arranque automático
sudo systemctl disable shany
```

---
*Fin Documentación de Arquitectura de Raspberry Pi - Shany AI*

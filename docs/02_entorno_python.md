# Paso 2: Configuración del Entorno Python

Para garantizar la fluidez y el aislamiento del proyecto Shany, utilizamos un **Entorno Virtual (venv)** con Python 3.

## 1. Creación del Entorno Virtual
Hemos creado un entorno aislado en la carpeta principal del usuario para evitar conflictos con el sistema.

```bash
# Crear el entorno venv
python3 -m venv shany_env

# Actualizar el gestor de paquetes (pip)
./shany_env/bin/pip install --upgrade pip
```

## 2. Instalación de Librerías
Se instalaron las bibliotecas necesarias para el procesamiento de audio y la comunicación con la API de ElevenLabs.

### Librerías de Audio:
- **`pyaudio`**: Interfaz para PortAudio (grabación y reproducción).
- **`sounddevice`**: Librería moderna para el manejo de streams de audio.

### Librerías de API:
- **`elevenlabs`**: Cliente oficial para la generación de voz sintética.
- **`python-dotenv`**: Para manejar las claves de API de forma segura.

```bash
./shany_env/bin/pip install pyaudio sounddevice elevenlabs python-dotenv
```

## 3. Estructura del Entorno
- **Ejecutable de Python:** `/home/ietsi/shany_env/bin/python`
- **Ubicación de librerías:** `/home/ietsi/shany_env/lib/python3.*/site-packages`

---
*Próximo paso: Fase 3 - Pruebas de integración de audio.*

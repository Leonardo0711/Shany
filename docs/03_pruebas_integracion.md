# Paso 3: Pruebas de Integración de Audio

Una vez configurado el sistema y el entorno virtual, realizamos pruebas funcionales para asegurar que el hardware I2S es accesible desde Python.

## 1. Prueba de Reproducción (Altavoz)
Utilizamos el script `test_playback.py` para generar una onda senoidal de 440Hz (Nota La) y reproducirla a través del MAX98357.

### Script de prueba:
```python
# test_playback.py
# (Genera un tono de 3 segundos y lo envía al stream de salida)
```

### Ejecución:
```bash
./shany_env/bin/python test_playback.py
```
**Resultado:** Se escuchó un tono claro y constante. Los logs de ALSA mostraron que se detectó correctamente la tarjeta `googlevoicehat`.

## 2. Prueba de Grabación (Micrófono)
Utilizamos el script `test_record.py` para capturar 5 segundos de audio del INMP441 y guardarlo en un archivo WAV.

### Ejecución:
```bash
./shany_env/bin/python test_record.py
```

### Verificación del Archivo:
El archivo generado `test_recording.wav` tiene un tamaño de **~431KB**, lo cual corresponde matemáticamente a 5 segundos de audio mono a 44.1kHz. Esto confirma que el flujo de datos del micrófono es correcto.

## 3. Consideraciones Técnicas
- **Latencia:** Los scripts responden casi instantáneamente al usar el entorno `venv` nativo.
- **Dispositivo por defecto:** El sistema ALSA ha sido configurado para que la tarjeta I2S sea el dispositivo 0 (hw:0,0), lo cual simplifica el código de Python al no tener que especificar el ID del dispositivo constantemente.

---
*Próximo paso: Implementación de la lógica de conversación con ElevenLabs.*

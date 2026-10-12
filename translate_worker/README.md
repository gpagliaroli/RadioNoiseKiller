# Módulo de Traducción

Proceso separado que la app principal lanza y con el que habla por
stdin/stdout. No forma parte del instalador de RadioNoiseKiller.

## Instalación (usuario normal): un clic

Pestaña **Traducción → "Instalar módulo de traducción"**. La app pide
confirmación (con el tamaño de la descarga, ~600 MB) y, solo si aceptás:

1. Baja un Python embebible (Windows) o crea un venv (Linux; necesita
   `python3-venv`: `sudo apt install python3-venv`).
2. Instala `requirements.txt` (faster-whisper, argostranslate, pins probados).
3. Descarga el modelo de voz (`tiny`, ~75 MB) y el paquete del idioma elegido.

Todo queda en `TraduccionRuntime/` junto a la app (`settings.json`). Después de
instalar funciona sin internet. **Desinstalar módulo** borra esa carpeta.
Si no apretás el botón, no se descarga nada.

El worker viaja dentro del bundle como datos (los `.spec` solo copian los
`.py`, nunca analizan faster-whisper); `src/translate_installer.py` los copia
al runtime en cada arranque del módulo, así una app nueva actualiza el worker
sin reinstalar el entorno.

## Rutas manuales (solo desarrollo)

Si `translate.worker_python_path` y `translate.worker_script_path` están cargadas en `settings.json`, tienen prioridad sobre el módulo instalado y el panel de instalación se oculta. No hay botón en la UI: para volver al módulo instalado, vaciá esas dos claves.

## Por qué está separado

RadioNoiseKiller es una app de DSP puro (numpy/scipy, sin IA). El runtime de
este módulo (`ctranslate2`, `onnxruntime`) agrega cientos de MB y está
**excluido a propósito** del instalador principal.

## Importante — qué esperar

La transcripción es una ayuda para hacerse una idea aproximada de un idioma
que no se conoce, **no un subtítulo confiable**. Con señal débil, fading o
ruido de banda, el resultado puede ser impreciso o directamente incorrecto.

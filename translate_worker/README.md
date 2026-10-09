# Módulo de Traducción — instalación (v1, manual)

Este proceso NO forma parte del instalador de RadioNoiseKiller. Es un
entorno Python separado que la app principal lanza y con el que habla por
stdin/stdout. Se instala una sola vez, a mano.

## Por qué está separado

RadioNoiseKiller es, aparte de esto, una app de DSP puro (numpy/scipy, sin
IA). El runtime que necesita este módulo (`faster-whisper`, `argostranslate`
y sus dependencias — `ctranslate2`, `onnxruntime`) agrega varios cientos de
MB y está **excluido a propósito** del instalador principal. Así quien no
use Traducción no paga ese costo.

## Instalación

1. Python 3.10+ (el mismo que use RadioNoiseKiller sirve, o cualquier otro).
2. Crear un entorno virtual propio, **no** el `.venv` de RadioNoiseKiller:
   ```
   python -m venv .venv_translate
   .venv_translate\Scripts\activate        (Windows)
   source .venv_translate/bin/activate     (Linux)
   pip install -r requirements.txt
   ```
3. En la pestaña "Traducción" de RadioNoiseKiller, configurar:
   - **Python del worker**: ruta a `.venv_translate\Scripts\python.exe`
     (o `.venv_translate/bin/python` en Linux).
   - **Script del worker**: ruta a este `worker.py`.
4. Primer uso: la primera vez que se activa la traducción, se descargan
   automáticamente el modelo de voz (`tiny` por defecto, ~75 MB) y, según el
   idioma detectado, el paquete de traducción correspondiente (50-200 MB por
   par de idiomas). Necesita internet solo esa primera vez por idioma — después
   queda cacheado localmente y funciona sin conexión.

## Importante — qué esperar

La transcripción es una ayuda para hacerse una idea aproximada de un idioma
que no se conoce, **no un subtítulo confiable**. Con señal débil, fading o
ruido de banda, el resultado puede ser impreciso o directamente incorrecto
— es una limitación de cómo funciona cualquier modelo de reconocimiento de
voz actual sobre audio de onda corta, no un bug para reportar.

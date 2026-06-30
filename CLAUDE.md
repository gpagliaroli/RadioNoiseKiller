# Reductor de Ruido Radio — contexto para Claude Code

## Descripción del proyecto

Software standalone de reducción de ruido con IA para radio AM/SSB (ham radio).
Stack: Python 3.14, PySide6, sounddevice, onnxruntime, scipy.

## Cómo ejecutar

```bash
# Desarrollo
.venv\Scripts\python.exe src\main.py

# Tests individuales
.venv\Scripts\python.exe tests\test_devices.py
.venv\Scripts\python.exe tests\test_dsp.py
.venv\Scripts\python.exe tests\test_model.py
.venv\Scripts\python.exe tests\test_pipeline.py

# Empaquetar
.venv\Scripts\python.exe -m PyInstaller reductor.spec --clean --noconfirm
```

## Estructura clave

```
src/
├── main.py              # Entrada: QApplication → MainWindow
├── config.py            # AppConfig (AudioConfig, DSPConfig, ModelConfig, GainConfig)
├── pipeline.py          # ProcessingPipeline: orquesta audio I/O + DSP + modelo
├── utils.py             # resource_path() y settings_path()
├── audio/
│   ├── devices.py       # list_devices() → solo WASAPI + WDM-KS, sin duplicados
│   └── stream.py        # AudioStream: wrapper sounddevice con callback
├── dsp/
│   ├── filters.py       # BandpassFilter (Butterworth IIR, stateful)
│   ├── gain.py          # GainLimiter (peak follower, ataque instantáneo)
│   └── level.py         # LevelMeter (RMS con decaimiento)
├── models/
│   └── deepfilternet.py # DeepFilterNet3: inferencia ONNX con ventana deslizante
└── ui/
    ├── main_window.py   # QTabWidget: Principal + Avanzada
    ├── advanced_tab.py  # Sliders de configuración avanzada
    ├── slider_row.py    # Widget: label + QSlider escalado a float + unidad
    └── vu_meter.py      # Widget VU meter custom (QPainter)
models/
├── enc.onnx             # Encoder DeepFilterNet3
├── erb_dec.onnx         # Decoder ERB (máscara espectral)
├── df_dec.onnx          # Decoder DF (filtrado profundo)
└── config.ini           # Hiperparámetros del modelo (sr=48000, hop=480, etc.)
```

## Decisiones de arquitectura importantes

### Modelo ONNX directo (sin pip install deepfilternet)
`deepfilternet` en PyPI requiere compilar `deepfilterlib` con Rust/Cargo.
Se usan los archivos ONNX pre-exportados directamente con `onnxruntime`.
Los modelos están en `models/` y se incluyen en el bundle PyInstaller via `reductor.spec`.

### Rutas de recursos con resource_path()
En bundle PyInstaller los archivos están en `sys._MEIPASS`, no en el CWD.
Siempre usar `from utils import resource_path` para rutas a `models/`.
Para settings.json usar `settings_path()` (escribe junto al .exe, no en _MEIPASS).

### Deduplicación de dispositivos de audio
PortAudio expone cada dispositivo físico 4 veces (MME, DirectSound, WASAPI, WDM-KS).
`audio/devices.py` filtra: WASAPI primero, WDM-KS solo para dispositivos sin WASAPI.
Importante: "Mezcla estéreo" (Stereo Mix) solo existe en WDM-KS — no descartarlo.

### Pipeline thread-safety
El callback de sounddevice corre en hilo de audio separado (alta prioridad).
Usar `self._lock` en pipeline.py para todos los accesos a `_bandpass` y `_limiter`.
El modelo DeepFilterNet3 NO usa el lock (es stateful y single-threaded por diseño).
`_input_gain` es float — escritura atómica en Python, no necesita lock.

### Resiliencia del hilo procesador (_run_processor)
`_run_processor` envuelve todo el cuerpo de procesado en try/except. Si ocurre una
excepción (NaN, shape mismatch, overflow numpy), el hilo **no muere**: notifica via
`_on_error` callback, resetea los buffers internos de todos los módulos DSP, y continúa
con el siguiente chunk. Sin esto, el hilo moría silenciosamente, `_in_queue` se llenaba,
y el aprendizaje del perfil de ruido quedaba atascado en 0 frames.

### Drenado de cola en stop()
`_in_queue` tiene maxsize=30 (~300ms de audio). Si el hilo procesador se cuelga o muere,
la cola se llena y `put_nowait(None)` (el sentinel de parada) falla silenciosamente.
`stop()` drena la cola después de detener el stream (seguro: sin audio nuevo llegando)
y luego pone el sentinel. Si el hilo sigue vivo tras join(timeout=2s), reintenta el drain
+ sentinel una vez más con join(timeout=1s).

### clear_profile() también resetea los buffers OLA
`NoiseProfiler.clear_profile()` limpia `_ola_prev` y `_ola_acc` además del perfil.
Antes solo reseteaba el perfil de ruido. Si los buffers OLA tenían valores extremos
(por impulsos muy fuertes durante el uso), esos valores se propagaban a frames
subsiguientes vía el overlap-add, pudiendo producir NaN o excepciones en el Wiener.

### Sliders live vs. requieren reinicio
- Live (se aplican inmediatamente): filtros DSP, ganancia entrada/salida, límite de picos
- Requieren reinicio: block_size (audio buffer), window_frames (buffer del modelo)
- `AdvancedTab.set_processing_active(True)` deshabilita solo los de reinicio.

### Ventana de procesamiento del modelo
El modelo no es streaming nativo. Se acumulan `window_frames` (default 10 = 100ms)
frames de 10ms, se procesa la ventana completa, y se emite el primer frame.
Latencia resultante: window_frames × 10ms + latencia de sounddevice (~40–80ms total).

## Parámetros del modelo (models/config.ini)

| Parámetro | Valor | Uso en código |
|-----------|-------|---------------|
| sr | 48000 | AudioConfig.sample_rate |
| hop_size | 480 | AudioConfig.block_size, ModelConfig.hop_size |
| fft_size | 960 | ModelConfig.fft_size |
| nb_erb | 32 | ModelConfig.nb_erb |
| nb_df | 96 | ModelConfig.nb_df |
| df_order | 5 | ModelConfig.df_order |
| df_lookahead | 2 | DeepFilterNet3.LOOKAHEAD |

## Configuración persistente

`AppConfig.save()` / `AppConfig.load()` → `settings.json`
Guardado automático con debounce de 800ms en `MainWindow._save_timer`.
En dev: `<raíz_proyecto>/settings.json`
En bundle: junto al `.exe`

## Tests disponibles

| Archivo | Qué verifica |
|---------|-------------|
| `tests/test_devices.py` | Enumeración y deduplicación de dispositivos |
| `tests/test_hostapis.py` | Listado completo por API (diagnóstico) |
| `tests/test_dsp.py` | BandpassFilter, GainLimiter, LevelMeter |
| `tests/test_model.py` | Carga ONNX, inferencia, benchmark de latencia |
| `tests/test_pipeline.py` | Pipeline completo simulado sin hardware |

## Estado del proyecto

**Fase 1 completa** — todas las funcionalidades MVP operativas y empaquetadas.
Distribuible: `dist\ReductorRuidoRadio_v1.0.zip` (88 MB) con `MANUAL_ReductorRuidoRadio_v1.0.pdf` incluido.

Pendiente para Fase 2:
- Visualizador de espectro en tiempo real
- Integración completa del `df_dec` (filtrado profundo, actualmente solo ERB mask)
- Soporte Linux

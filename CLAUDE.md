# Reductor de Ruido Radio — contexto para Claude Code

## Descripción del proyecto

Software standalone de reducción de ruido para radio AM/SSB (ham radio).
Stack: Python 3.10+, PySide6, sounddevice, scipy, numpy.
Todo el DSP es numpy/scipy puro — sin dependencias de IA, ONNX ni modelos externos.

## Cómo ejecutar

```bash
# Desarrollo (Windows)
.venv\Scripts\python.exe src\main.py

# Desarrollo (Linux / Raspberry Pi)
.venv/bin/python src/main.py

# Tests individuales
.venv\Scripts\python.exe tests\test_devices.py   # Windows
.venv/bin/python        tests/test_devices.py    # Linux/Pi

# Empaquetar (Windows — genera dist/ReductorRuidoRadio/)
.venv\Scripts\python.exe -m PyInstaller reductor.spec --clean --noconfirm

# Empaquetar (Linux x86_64 o Raspberry Pi ARM64 — mismo spec)
.venv/bin/python -m PyInstaller reductor-linux.spec --clean --noconfirm
```

## Setup en Raspberry Pi (primera vez)

```bash
# Prerrequisitos del sistema
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip libportaudio2 libxcb-xinerama0

# Entorno virtual
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install sounddevice numpy scipy PySide6 pyinstaller

# Ejecutar directamente (sin bundle)
.venv/bin/python src/main.py

# O empaquetar como bundle autónomo
.venv/bin/python -m PyInstaller reductor-linux.spec --clean --noconfirm
```

> **Nota display Pi:** si usás VNC o SSH con reenvío X11, asegurarse de que `DISPLAY`
> esté definido (`export DISPLAY=:0` para VNC local, o usar `DISPLAY=localhost:10.0` en SSH -X).

## Estructura clave

```
src/
├── main.py              # Entrada: QApplication → MainWindow
├── config.py            # AppConfig (AudioConfig, DSPConfig, GainConfig, WindowConfig)
├── pipeline.py          # ProcessingPipeline: orquesta audio I/O + DSP
├── utils.py             # resource_path() y settings_path()
├── audio/
│   ├── devices.py       # list_devices() → filtra por API según OS (WASAPI/WDM en Win, ALSA en Linux)
│   └── stream.py        # AudioStream: wrapper sounddevice con callback
├── dsp/
│   ├── agc.py           # AGC (control automático de ganancia)
│   ├── anf.py           # AdaptiveNotchFilter (cancela heterodinos/tonos)
│   ├── exciter.py       # AuralExciter (armónicos tanh)
│   ├── filters.py       # BandpassFilter + PresenceFilter (Butterworth IIR, stateful)
│   ├── freq_shift.py    # FrequencyShifter (corrección de pitch SSB)
│   ├── gain.py          # GainLimiter (peak follower, ataque instantáneo, expone last_reduction_db)
│   ├── level.py         # LevelMeter (RMS con decaimiento)
│   └── noise_profiler.py # NoiseProfiler (Log-MMSE DD + MCRA adaptativo, dos modos seleccionables)
└── ui/
    ├── main_window.py   # QTabWidget: Principal + Avanzada Audio + Avanzada Ruido + Espectro
    ├── advanced_tab.py  # Sliders de configuración avanzada
    ├── slider_row.py    # Widget: label + QSlider escalado a float + unidad
    ├── vu_meter.py      # VU meter custom (QPainter), texto doble-clip oscuro/claro
    └── spectrum_widget.py  # Visualizador de espectro en tiempo real (FFT + EMA, 15 fps)
```

## Decisiones de arquitectura importantes

### Rutas de recursos con resource_path()
En bundle PyInstaller los archivos están en `sys._MEIPASS`, no en el CWD.
Usar `from utils import resource_path` para cualquier recurso empaquetado.
Para settings.json usar `settings_path()` (escribe junto al .exe, no en _MEIPASS).

### Deduplicación de dispositivos de audio (Windows)
PortAudio expone cada dispositivo físico 4 veces (MME, DirectSound, WASAPI, WDM-KS).
`audio/devices.py` filtra: WASAPI primero, WDM-KS solo para dispositivos sin WASAPI.
Importante: "Mezcla estéreo" (Stereo Mix) solo existe en WDM-KS — no descartarlo.
En Linux (incluyendo Raspberry Pi) PortAudio usa ALSA — `devices.py` debe detectar el OS
y no aplicar el filtro WASAPI/WDM en ese caso.

### Pipeline thread-safety
El callback de sounddevice corre en hilo de audio separado (alta prioridad).
Usar `self._lock` en pipeline.py para todos los accesos a `_bandpass` y `_limiter`.
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
- Requieren reinicio: block_size (audio buffer)
- `AdvancedTab.set_processing_active(True)` deshabilita solo los de reinicio.

### Control de Intensidad del cancelador (noise_alpha)
`alpha` se aplica como `gain_out = gain_omlsa ** alpha` al final del proceso, no dentro del
estimador DD. Motivo: si `alpha` escala `noise_power` en el DD, la etapa OMLSA ancla los bins
de ruido a `floor` de todas formas, haciendo el slider casi inaudible. Con la fórmula potencial:
- `alpha=0` → passthrough (gain=1 para todos los bins)
- `alpha=1` → reducción plena (comportamiento OMLSA sin modificar)
- Bins de voz con gain≈0.9: `0.9^0.7 ≈ 0.93` → impacto mínimo en la voz
- Bins de ruido con gain≈0.1: `0.1^0.7 ≈ 0.17` → reducción notable incluso a valores medios
El estimador DD trabaja sobre el SNR real (sin escalar por alpha), mejorando la precisión del VAD.

### Estimador Log-MMSE (Ephraim-Malah 1985)
El bloque de ganancia usa el estimador de mínima distorsión log-espectral, no el MMSE clásico:
```
g_wiener[k] = SNR_prior[k] / (SNR_prior[k] + 1)
v[k]        = g_wiener[k] · SNR_post[k]
gain_dd[k]  = clip( g_wiener[k] · exp(½·E₁(v[k])), floor, 1.0 )
```
- Para SNR bajo (bins de voz débil): `gain_dd >> g_wiener` → menos supresión en voz
- Para SNR alto (voz clara): `exp(½·E₁(v)) → 1` → idéntico al Wiener clásico
- Implementado con `scipy.special.exp1`; overhead ~76µs por frame (< 1% a 10ms/frame)

### MCRA — estimación adaptativa de ruido
Modo alternativo al perfil estático, seleccionable en la UI sin reinicio del stream.
No requiere aprendizaje manual; estima el piso de ruido continuamente usando mínimos
espectrales en ventana deslizante.

Parámetros: B=4 subtramas × M=20 frames/subtrama → ventana ~800ms; warmup ~200ms.
```
S_f[k]   = 0.9·S_f_prev + 0.1·|Y[k]|²          (suavizado)
S_min[k] = mín de B·M frames de S_f             (seguimiento de mínimos)
I_min[k] = S_f[k]/S_min[k] > 1.67               (indicador de habla)
α_d[k]   = 0.85 + 0.15·I_min[k]                 (α=0.85 sin habla → actualiza; α=1.0 con habla → congela)
λ_d[k]   = α_d·λ_d_prev + (1−α_d)·|Y[k]|²      (estimado de ruido)
noise_mag = sqrt(λ_d)
```
Ambos modos alimentan el mismo bloque Log-MMSE + OMLSA; solo cambia la fuente de `noise_mag`.
`config.py`: campo `noise_mode: str = "static"|"mcra"` en `DSPConfig`, persistido en settings.json.

## Configuración persistente

`AppConfig.save()` / `AppConfig.load()` → `settings.json`
Guardado automático con debounce de 800ms en `MainWindow._save_timer`.
En dev: `<raíz_proyecto>/settings.json`
En bundle: junto al `.exe` / `.bin`

## Tests disponibles

| Archivo | Qué verifica |
|---------|-------------|
| `tests/test_devices.py` | Enumeración y deduplicación de dispositivos |
| `tests/test_hostapis.py` | Listado completo por API (diagnóstico) |
| `tests/test_dsp.py` | BandpassFilter, GainLimiter, LevelMeter |
| `tests/test_pipeline.py` | Pipeline completo simulado sin hardware |

## Estado del proyecto

**Fase 1 + Espectro + mejoras DSP completos** — todas las funcionalidades MVP operativas.
Distribuible v1.1 en GitHub Releases. Manual fuente en `MANUAL.md` — regenerar PDF para v1.2.

Cambios v1.2 (pendiente de release):
- MCRA: estimación adaptativa de ruido, seleccionable vs. perfil estático en la UI
- Log-MMSE: reemplaza MMSE-STSA en el estimador de ganancia DD (voz más natural)
- Piso MCRA en espectro: línea amarilla se actualiza cada 500ms con el estimado adaptativo
- Indicador del limitador de picos: label en tiempo real junto al slider (naranja/rojo cuando activo)

### Visualizador de espectro — decisiones de implementación

**Captura de spec_pre en pipeline:** `spec_pre_frames` se llena después del bandpass+ANF y antes del
cancelador de ruido. Así la curva "Entrada" muestra exactamente lo que ve el Wiener, con el mismo
ancho de banda que la curva "Salida" — evita que la entrada aparezca más alta que la salida.

**Piso de ruido (línea amarilla):** se toma un snapshot de `_ema_pre` al llamar `stop_floor_learning()`,
no un acumulado. Con ALPHA=0.35 y 5 segundos el EMA está completamente convergido.

**GIL y CPU:** el timer corre a 15 fps (67ms). `_tick()` devuelve inmediatamente si `isVisible()` es
False (tab no activo). Las curvas se dibujan con `QPolygonF` + `drawPolyline`/`drawPolygon` en lugar de
N llamadas `lineTo()` sobre `QPainterPath`, eliminando la contención de GIL con el hilo de audio.

**WindowConfig:** `spectrum_db_max` y `spectrum_max_freq_hz` se persisten en `settings.json`
bajo la clave `"window"` junto con la posición de la ventana.

Pendiente para Fase 2:
- Validar build en Pi real (ARM64 Raspberry Pi OS Bookworm)
- Soporte de múltiples canales de audio

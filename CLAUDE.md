# RadioNoiseKiller (ex "Reductor de Ruido Radio") — contexto para Claude Code

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

# Empaquetar (Windows — genera dist/RadioNoiseKiller/)
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
│   └── noise_profiler.py # NoiseProfiler (Log-MMSE DD + MCRA adaptativo + pitch enhance SSB)
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

### Pitch enhancement SSB (autocorrelación + máscara armónica)
Feature opcional para señales SSB débiles. Funciona sobre `p_speech` justo antes de OMLSA:
- Buffer rolling de 2048 muestras (~42ms) siempre actualizado, detección lazy.
- `_detect_pitch()`: autocorrelación normalizada vía FFT (4096-point), búsqueda en lag=120..600 (80–400 Hz).
  Retorna f0 solo si el pico de autocorr ≥ 0.30 (umbral de confianza).
- `_harmonic_mask(f0)`: Gaussiana (σ=1.5 bins) centrada en cada k·f0, clipeada a [0,1].
- Integración: `p_speech = max(p_speech, hmask · strength)` — solo eleva, nunca baja.
  Esto previene que el cancelador suprima bins de armónicos en señales con SNR muy bajo.
- Hold de 3 frames: el último f0 válido se conserva 3 frames ante gaps de detección.
- Sin efecto si f0 no detectado o pitch disabled (passthrough).
- `pitch_enhance_enabled / pitch_enhance_strength` en DSPConfig; checkbox en `MainWindow._build_modules_group()` (sub-módulo indentado bajo el cancelador), slider de sensibilidad en `AdvancedNoiseTab`.

### Post-filtro espectral (ruido musical residual)
Segunda pasada sobre los bins de ruido después de OMLSA+alpha para eliminar el ruido musical
("pitidos fantasma") que el Wiener deja cuando el VAD marcó el bin como ruido pero no lo suprimió
del todo. Fórmula: `gain_post[k] = gain[k]^(1 + strength·(1 − p_speech[k]))`.
- Bins de voz pura (`p_speech=1`): sin cambio — el exponente es 1, gain no cambia.
- Bins de ruido puro (`p_speech=0`): `gain^(1+strength)` → mayor supresión cuanto mayor sea `strength`.
- Bins intermedios: supresión gradual proporcional a `1 - p_speech[k]`.
- Aplicado después del suavizado en frecuencia y del paso alpha, antes de `spec_out = gain·spec`.
- `post_filter_enabled / post_filter_strength` en DSPConfig; checkbox en `MainWindow._build_modules_group()` (sub-módulo indentado bajo el cancelador), slider en `AdvancedNoiseTab`.
- **IMPORTANTE — no clampear con `_eff_floor` después del post-filtro.** El `np.maximum` final debe usar
  un suelo bajo (`0.005`, −46 dB) para proteger de underflow, NO `_eff_floor`. Clampear con el piso
  espectral (0.10 = −20 dB) devuelve todos los bins suprimidos al nivel del piso y anula silenciosamente
  toda la supresión extra — el slider de agresividad no tiene efecto audible. El `_eff_floor` ya fue
  aplicado antes por OMLSA y no debe re-aplicarse después de una etapa de supresión adicional.

### Compensación de fading HF (noise_fading_comp)
Para onda corta con QSB. Dos mecanismos, ambos activos solo con el checkbox habilitado
(sub-módulo del cancelador en Módulos Activos, pestaña Principal — v1.3):
- **Freeze MCRA:** si la energía del frame cambia ≥ umbral respecto al EMA (slider "Sensibilidad
  fading" 2–10 dB, default 5; EMA con alpha=0.80 fijo), se congela `λ_d` por N frames (slider
  "Duración del freeze" 100–500 ms, default 200; `_fading_freeze_frames = round(ms / hop_ms)` —
  se recalcula en `reset(hop)`, invariante 9). Evita que MCRA siga al nivel de señal durante el
  fade y quede desfasado al volver. Ambas transiciones (fade y recovery) disparan el freeze.
- **Release DD acelerado:** en bins con SNR subiendo, `beta_eff` usa `_FADING_BETA_RELEASE=0.45` en vez
  de `beta_fast` (0.80) → la ganancia Wiener responde en ~2-3 frames en vez de 10-15. Elimina el
  "llega tarde" al salir del fade. **Solo durante un evento activo (`_fading_active`)** — la
  recuperación dispara su propia ventana de freeze, así que la voz que vuelve del fade queda cubierta.
  (Antes aplicaba siempre con el checkbox activo: con mucho ruido y sin fading real, los falsos
  positivos del detector de bins subían con β=0.45 → gorgojeo extra audible — reportado en 40m local.
  Test de regresión: sin eventos, comp ON == comp OFF salida idéntica.) Fijo, no expuesto.
- Detección en `process()` ANTES de `_mcra_update()` (el freeze debe estar activo al entrar).
  Ojo: por el OLA al 50%, un fade tarda 2 frames en verse completo en la energía del frame.
- Solo tiene efecto en modo MCRA; en estático el freeze no aplica (no hay estimador que congelar).
- `noise_fading_comp / noise_fading_change_db / noise_fading_freeze_ms` en DSPConfig, persistidos en
  settings.json y presets. Indicador "FADE"/"ok" y ambos sliders en Avanzada Cancelador
  (`fading_active` property → pipeline → `_update_stats()`); sliders habilitados solo con
  cancelador + checkbox activos.

### Invariantes a mantener (lecciones de la revisión pre-v1.2)

Bugs reales encontrados en revisión — cada uno es un patrón que puede reaparecer:

1. **Clamp del setter == rango del slider.** Al ampliar el rango de un SliderRow, actualizar también
   el `np.clip` del setter correspondiente en `NoiseProfiler`/pipeline. Ocurrió dos veces:
   `set_pf_boost` clampeaba a 1.5 con slider a 2.5 (la mitad superior del slider no hacía nada), y
   antes `set_post_filter_strength` a 3.0 con slider a 4.0. El bug es silencioso: la UI muestra el
   valor nuevo pero el DSP usa el recortado.
2. **El squelch requiere `_noise_enabled`.** `voice_prob_sq` solo se actualiza dentro de
   `NoiseProfiler.process()` con el cancelador activo. Sin ese chequeo, desactivar el cancelador con
   squelch activo congela el vp y el gate puede cerrar para siempre (silencio total sin indicación).
   La condición vive en `_run_processor` Y en la property `squelch_gate_open` — mantener ambas en sync.
3. **Las properties de estado deben reflejar las condiciones reales del procesamiento.**
   `squelch_gate_open` reportaba CERRADO cuando el bloque real de squelch ni corría (sin perfil).
   Si un indicador se calcula fuera del hilo DSP, replicar TODAS las condiciones del bloque real.
4. **`is_running` es método, no property** — `if pipeline.is_running:` siempre es True (bound method
   truthy). Escribir `is_running()`.
5. **Los indicadores de `_update_stats()` deben actualizarse siempre**, no detrás de un early-return
   condicional (quedan con valores viejos, p. ej. tras "Borrar perfil"). Usar if/else, no return.
6. **Features condicionadas a un modo deben chequear el modo en TODOS sus efectos.** El
   `beta_release` de fading comp aplicaba en modo static aunque la detección solo corre en MCRA.
   Además, al salir del modo (set_mode) resetear el estado del feature (`_fading_active` quedaba
   pegado en True).
7. **Race aceptada:** `pop_blanker_hits` (lectura+reset no atómico) se deja sin lock a propósito —
   proteger un contador de diagnóstico no justifica contención en el hilo de audio. No "arreglarlo".
8. **`default=` de SliderRow es el valor de fábrica, no el de la config.** El parámetro `default`
   alimenta el menú "Restaurar por defecto" (click derecho). Pasar `self._config.x` hace que el
   default sea lo que quedó de la sesión anterior. Usar `_DSP_DEF`/`_AUDIO_DEF`/`GainConfig()` y
   cargar la posición inicial aparte vía `_load_values()` / `set_value()`.
9. **Todo array por-bin debe redimensionarse en `reset(hop_size)`.** Al agregar estado con tamaño
   `self._nb` (como `_floor_curve`), incluirlo en el bloque de resize de `NoiseProfiler.reset()`.
   Un array con tamaño viejo produce shape mismatch tras cambiar el tamaño de bloque, y el error
   handler de `_run_processor` resetea el profiler en loop — MCRA nunca completa el warmup y el
   síntoma es "nunca termina de calibrar" (sin mensaje de error visible). Módulos con estado
   dependiente del hop (AGC) también deben actualizarse en `pipeline.start()`.
10. **Las claves ausentes de un preset usan el DEFAULT de fábrica, no el valor vivo del config.**
   `PresetManager._apply_to_config` hace `d.get(clave, ddef.X)` con `ddef = DSPConfig()` fresco
   (ídem `GainConfig()`); los dicts de `bandpass_limits`/`bandpass_out_limits` parten de una copia
   de los defaults y el preset los pisa, así un modo ausente también vuelve a fábrica. Con el
   fallback al valor vivo, un preset viejo al que le falta un campo agregado después heredaba lo
   que hubiera en la sesión → no coincidía con `snapshot()` (que normaliza desde un `AppConfig`
   limpio) → **"(modificado)" espurio permanente**. Mordió 4 veces (`agc_*` en v1.8,
   `voice_leveler_*` en v1.8.2, `noise_mcra_window_ms`/`noise_hf_boost` en v1.9). Regenerar los
   presets de fábrica al agregar un campo sigue siendo lo prolijo, pero ya no es obligatorio para
   que la comparación funcione. Tests: `test_presets::test_missing_keys_use_factory_defaults` y
   `::test_missing_bandpass_mode_uses_default`.
11. **Los tests nunca escriben en los datos reales del usuario.** Todo dato escribible de la app
   (`settings.json`, `Presets/`, `PerfilesRuido/`, `Grabaciones/`) sale de `utils.data_dir()`, que
   respeta la env var **`RNK_DATA_DIR`**. `run_all.py` la fija a un temp dir por suite y `test_ui`
   crea el suyo si corre solo (con un `assert` de red de seguridad: si las rutas caen dentro del
   proyecto, el módulo rompe antes de tocar nada). Sin la variable el comportamiento es idéntico
   al de siempre. Motivo: `MainWindow` usa las carpetas reales, así que un test de UI podía
   sobrescribir/borrar presets de fábrica (afinados en el aire, no regenerables). Efecto secundario
   del mismo aislamiento: **`QSlider.setValue()` no emite `valueChanged` si el valor no cambia** —
   con el `settings.json` real, un test que seteaba el valor ya persistido no disparaba el handler
   y fallaba sin bug (pasó con `post_filter_strength=4.0` en
   `test_post_filter_on_principal_autoenable`, falla intermitente según el estado del disco). Al
   testear un handler de slider, partir de un valor distinto conocido.

**v2.0 publicada (agosto 2026)** — release en GitHub con distribuibles Windows y Linux. Versión de
app 2.0.0, manuales `MANUAL_RadioNoiseKiller_v2.0.pdf` (ES, 37 págs) y `..._v2.0_EN.pdf` (EN, 36
págs). Título "v2.0 by LU6APA". **Salto de mayor, no de menor**: cambió el corazón del cancelador y,
sobre todo, **el significado numérico de varios controles** (Post-Filtro, Intensidad, Mezcla del
excitador). Los presets de 1.9.x cargan sin error pero no suenan igual — los 8 de fábrica se
reajustaron en el aire. Todo el contenido de abajo se validó escuchando en la radio, con varias
iteraciones de ida y vuelta (ver los "reportado en el aire" de cada ítem: casi todos los fixes de
esta versión salieron de una escucha que contradijo una medición sintética).

**v2.1 publicada (agosto 2026)** — release en GitHub con distribuibles Windows y Linux. Versión de
app 2.1.0, manuales `MANUAL_RadioNoiseKiller_v2.1.pdf` (ES, 38 págs) y `..._v2.1_EN.pdf` (EN, 38
págs). Título "v2.1 by LU6APA". Release de menor: no cambia el DSP del cancelador ni el significado
de ningún control (los presets de la v2.0 suenan igual). Junta cinco tandas: la cascada que había
quedado fuera de alcance en la v1.8, el techo de ruido del AGC, el seed de presets de fábrica que
faltaba en los distribuibles, el job de compilación ARM64 (experimental) y la tanda de
accesibilidad. Los cinco bloques que siguen son el detalle de esta versión.

**v2.1 — cascada — profundidad, escala de color y marcadores.** Cierra
los tres ítems que habían quedado fuera de alcance en la v1.8.
- **Profundidad ajustable** (combo 15/30/60/120 s en la barra del espectro, persistida en
  `WindowConfig.waterfall_history_sec`). El ring se dimensiona SIEMPRE para el máximo (120 s ≈
  7 MB) y la profundidad solo cambia **cuántas filas se dibujan**: así ampliar la ventana muestra
  historia que ya estaba capturada, en vez de reasignar el buffer y perderla. El paso del eje de
  tiempo se adapta (5/10/15/30 s) para no amontonar etiquetas.
- **Escala de color en el margen SUPERIOR, no a la derecha.** `_ML`/`_MR` tienen que seguir siendo
  los mismos que en `SpectrumWidget` — de eso depende que los ejes de frecuencia de los dos
  gráficos queden alineados, que fue el punto de diseño original de la cascada. `_MT` sí se puede
  crecer sin desalinear nada (4 → 15 px), y ahí entran la barra de degradado y la etiqueta de
  fuente, que antes se dibujaba **encima** de la fila más nueva.
- **Marcadores de heterodino**: `AdaptiveNotchFilter` ahora expone `tone_freqs` (antes solo el
  conteo `notched_bins`); el pipeline lo publica y `_tick_levels` se lo pasa a la cascada, que
  dibuja marcas rojas sobre el eje de frecuencia. Se lee sin lock: es diagnóstico y el peor caso es
  un frame viejo (invariante 7). Solo se alimenta con la cascada visible — si está oculta es
  trabajo tirado. Sin ANF activo, `tone_freqs` devuelve None y no hay marcas.
- Verificado headless renderizando a QPixmap y contando píxeles del marcador (con tonos: aparece;
  sin tonos: cero). Test en `test_ui`.

**v2.1 — techo de ruido del AGC.** Reportado en el aire: *"con baja señal
el AGC sube la salida a −20 dB y queda un ruido molesto"*. El AGC de entrada lleva lo que mida a su
target **sin distinguir voz de ruido**, y tiene hasta **+36 dB**: medido, tras el fin de una
transmisión se va a 35.4 dB persiguiendo el ruido. El nivelador de voz no era el culpable (el
usuario probó sacarle el modo continuo y no cambió nada).
- Fix: `AGC.set_max_gain_limit(db)` — tope de ganancia adicional al del preset, calculado por el
  pipeline como `techo_dBFS − piso_de_ruido_de_entrada`. `agc_noise_ceiling_enabled/_db` en
  DSPConfig; checkbox + slider + indicador "Tope aplicado" en Avanzada Audio.
- El piso de ruido se mide sobre la entrada **CRUDA (pre-AGC)**: si se midiera después del AGC, el
  tope dependería de la ganancia que está limitando y se realimentaría.
- **El seguidor tiene que ser mínimo por VENTANA DESLIZANTE, no mínimo con decaimiento.** La primera
  versión usaba un mínimo que sube 0.2%/frame; eso trepa ~1.7 dB/s hacia el nivel de la señal, así
  que con voz continua **mide la voz, no el ruido**. Medido con voz a −20 dBFS y ruido a −40:
  marcaba **−28 dBFS**, a mitad de camino. Reportado en el aire: *"el piso que detecta incluye voz,
  el piso marcado es lo que indica el VU"*. Con subtramas + mínimo global (el patrón que ya usa
  MCRA, ventana ~4 s, EMA corto de 30 ms para que las pausas entre palabras registren): **−39.4 dBFS**,
  a 0.6 dB del real. Ventana en frames → depende del hop, se recalcula en `start()` (invariante 9).
  Test en `test_pipeline`.
- **El indicador debe decir si el límite está ACTUANDO, no solo su valor.** Mostraba "máx +0 dB" en
  rojo con entrada fuerte y el usuario lo leyó como un error — y tenía razón en que no informaba:
  con señal fuerte el AGC no quiere amplificar, así que ese tope no limita nada. Ahora muestra el
  piso medido y distingue *"sin efecto"* de *"limitando a +X dB"*.
- Medido con voz a −46 dBFS y ruido a −56: con techo −45 dBFS el ruido tras la transmisión pasa de
  −54.7 a **−77.9 dB** (−23 dB) y la voz solo baja 4 dB (el nivelador post-cancelador recupera el
  resto). Con techo −55 (por debajo del piso real de entrada) la voz se ahoga: −62 dB. **Por eso el
  indicador**: en 0 dB (rojo) el techo está limitando de más.
- **Se descartó, por medición, "congelar el AGC cuando no hay voz"**, que era la idea intuitiva:
  da −22 dB de ruido pero **se traba**. El VAD trabaja sobre la señal ya amplificada por el AGC; con
  la ganancia congelada baja, el vp se queda en 0.01–0.12, el hold no se libera nunca y la voz que
  vuelve queda **21 dB abajo** (medido). Es la MISMA trampa que el freeze de MCRA por vp. **Regla
  (segunda vez): un lazo de control no puede tomar su decisión de liberarse a partir de una señal
  que él mismo está atenuando.** Un tope no tiene el problema porque el AGC nunca deja de adaptar.
- Tests: `test_dsp` (el tope limita y NO congela — con señal fuerte el AGC sigue bajando) y
  `test_ui` (gating del slider por el checkbox, y que el control esté en la pestaña Principal).
- El control vive en **Principal → grupo Control, debajo del combo de AGC** (pedido del usuario:
  es un ajuste del AGC y se calibra escuchando). No está en Avanzada Audio.
- **Descartado — auto-mute por temporizador.** El usuario había propuesto mutear la salida tras N
  segundos sin señal, para la radio prendida sin nadie transmitiendo. Con el techo puesto dejó de
  hacer falta: *"ya no tiene sentido, la implementación actual es buena y suficiente"*. **No
  reproponerlo** salvo que aparezca un síntoma nuevo que el techo no cubra.
- Beneficio secundario que notó el usuario en el aire: **también ayuda con S/N baja**. Tiene
  sentido — el AGC deja de amplificar una señal que es mayormente ruido, así que el cancelador
  recibe algo más limpio.

**v2.1 — los presets de fábrica no llegaban al usuario final.**
Detectado por el usuario mirando el zip publicado: **los dos distribuibles de la v2.0 salieron sin
ningún preset**. El de Windows con la carpeta `Presets/` **vacía** —la crea el propio smoke test al
ejecutar el exe, así que *parece* correcta— y el de Linux directamente sin la carpeta. Los assets
del release ya se corrigieron re-empaquetando (sin tocar el binario), pero el problema de fondo era
estructural: **`resource_path()` y `presets_dir()` NO son la misma carpeta en un bundle** —
los recursos empaquetados viven en `_MEIPASS` (`_internal/`) y la carpeta de presets es escribible,
junto al ejecutable. Agregar los presets a `datas` del spec no alcanza: quedan en `_internal/Presets`,
donde la app no los busca.
- Fix: los dos specs empaquetan `Presets/*.json` como recurso y `utils.seed_factory_presets()` los
  copia a la carpeta escribible en el primer arranque (solo si no hay ningún `.json`, para respetar
  a quien borró alguno a propósito). Se llama desde `MainWindow.__init__` antes de crear el
  `PresetManager`.
- Tests en `test_presets`: el seed copia y no vuelve a pisar; y los dos specs empaquetan los JSON.
- Skill de release: paso nuevo que obliga a **verificar el contenido del zip** (presets, PDFs y
  binario) antes de publicar. **Regla: verificar que el artefacto contenga lo que debe, no solo que
  el build haya terminado bien.** Una carpeta vacía creada por el smoke test se ve igual que una
  carpeta correcta en un listado.

**v2.1 — build ARM64 (Raspberry Pi), experimental.** Job `build-arm64` en
`.github/workflows/build-linux.yml`, `runs-on: ubuntu-22.04-arm`, Python 3.12, `continue-on-error`.
Es **opt-in**: solo corre por `workflow_dispatch` con el input `arm64` en true — un runner ARM es
facturable y no se justifica en cada tag hasta que alguien confirme que el binario arranca en una Pi.
- Verificado que **COMPILA**: ELF aarch64 de 64 bits, 542 entradas, los 7 presets, plugins wayland
  presentes, `libasound` fuera del bundle. ~2 min. Python 3.12 en aarch64 tiene wheels de PySide6,
  scipy y numpy, así que no compila nada desde fuente — que era el riesgo principal.
- **Sin verificar que ARRANQUE en una Pi real** — por eso el paquete lleva `EXPERIMENTAL.txt` y no
  se publica como asset del release. Glibc: el runner es 22.04 (2.35), Bookworm es 2.36 → el binario
  debería correr, pero hay que probarlo.
- **Diagnóstico mal hecho tres veces, anotado para no repetirlo:** las cancelaciones de runs no eran
  la cuota de Actions ni el job ARM. La anotación del job lo decía: *"The job was not acquired by
  Runner of type hosted even after multiple attempts"* — GitHub no conseguía asignar runner, era
  transitorio, y al rato el mismo workflow corrió solo y terminó en success. **Leer la anotación del
  job antes de teorizar sobre facturación.**

**v2.1 — accesibilidad y ayuda en la UI.** Tres pedidos del usuario.
- **"Nivelar en continuo (música)" pasa a Principal → grupo Control**, entre el combo de AGC y el
  Techo de ruido. No es un ajuste que se deja puesto: se cambia según lo que se esté escuchando
  (música vs. voz), así que tiene que estar a la vista. Sigue gateada por cancelador + nivelador
  (invariante 2) vía `_refresh_control_gating()`, que corre al construir, al togglear un módulo y
  al cargar un preset.
- **Tooltip en los 45 sliders.** Los textos viven en `src/ui/tooltips.py`, en una tabla indexada
  por el NOMBRE DEL ATRIBUTO del `SliderRow`, y `apply_tooltips(self)` corre tras construir cada
  tab. Están aparte —y no en cada llamada al constructor— porque las tabs de Avanzadas ya son
  archivos de 1000+ líneas y así el texto se lee, se revisa y se traduce junto.
  **`SliderRow.setToolTip` tuvo que empezar a propagar a los hijos** (label / slider / valor): sobre
  el contenedor el tooltip no aparece casi nunca, porque el mouse siempre está encima de alguno de
  los tres — y justo sobre la barra, que es donde el usuario apunta, no se mostraba. Mismo patrón
  que `set_enabled`, que ya tenía el problema resuelto. Guard: `test_all_sliders_have_tooltip`
  exige tooltip no vacío **sobre el QSlider** en los SliderRow de la ventana y de las tres tabs.
- **Escala de la interfaz (100 / 125 / 150 %)**, combo en la barra de estado al lado del idioma;
  default 100 % = idéntico a siempre. `window.ui_scale` en settings.json; `main.py` la lee con
  `config.read_ui_scale()` y la exporta a **`QT_SCALE_FACTOR` ANTES de crear el `QApplication`**
  (después no tiene efecto) — por eso el lector es una función aparte, sin Qt y tolerante a un
  settings.json roto: un JSON inválido no puede impedir que la app abra. Requiere reinicio, como
  el idioma.
  - **Se eligió escalar TODO y no solo la fuente** porque la UI está construida en píxeles fijos:
    60 `setFixedWidth/Height`, `SliderRow` con label 150 / barra 400 / valor 72, y la ventana con
    ancho FIJO en 770 (regla de UX de v1.9.1). Con `QT_SCALE_FACTOR` la geometría **lógica no
    cambia** (verificado: la ventana sigue midiendo 770 y los labels 150) y Qt renderiza más
    grande contra esos mismos números, así que los anchos fijos siguen valiendo y nada se corta.
    Agrandar solo la fuente habría requerido convertir esos 60 anchos a métrica de fuente.
  - **El combo ofrece solo las escalas que ENTRAN en la pantalla** (`ui_scales_that_fit`, función
    pura y testeada): a mayor escala la ventana ocupa más pantalla aunque su ancho lógico no
    cambie, así que la comparación va en píxeles REALES. En 1366 entran las tres; en 1024 se cae
    el 150 %. Y si el usuario se muda a un monitor más chico, `_restore_or_center` **vuelve a
    100 % para el próximo arranque y avisa** — como el ancho es fijo Qt no puede achicar la
    ventana, y la barra de estado (donde vive el combo para deshacerlo) quedaría fuera de pantalla.
  - **Descartado — subir los indicadores de 7/8 pt.** Los 31 `font-size` inline escalan
    proporcionalmente, así que a 100 % siguen siendo los textos más chicos de la pantalla; se le
    ofreció al usuario subirlos y respondió que **no hace falta** (el reclamo era general, no sobre
    esos indicadores). No reproponerlo salvo que llegue un pedido puntual sobre ellos.
  - Verificado con la app real a 125 % y las tres escalas headless (dpr sigue a `QT_SCALE_FACTOR`,
    ancho lógico invariante). **Validado visualmente por el usuario en su monitor** — junto con el
    movimiento del checkbox y los tooltips de los 45 sliders.

## Cambios de la v2.0

**Post-filtro rediseñado + anti-gorgojeo automático** (investigación de agosto 2026; medido en
simulación, **pendiente de validación en el aire**):

- **El post-filtro ya no exponencia la ganancia.** `gain^(1+s·(1−p))` multiplica por (1+s) la
  fluctuación EN dB del ruido: con s=6 los ~6 dB de fluctuación natural salían a ~18 dB, y cada
  bin que sobrevivía pegaba un pico aislado — **esa era la fuente dominante del gorgojeo con solo
  ruido**, no el MCRA. Además castigaba los bins de voz con `p_speech` intermedio (p=0.5 →
  `gain⁴`), que es por qué había que bajar la Intensidad para compensar. Ahora **resta una cantidad
  fija de dB** en los bins de ruido: `gain · 10^(−4.5·s/20)^(1−p)`, tope −60 dB
  (`_POST_DB_PER_UNIT`, `_POST_MIN_GAIN`). Mismo slider, mismo rango 0–10, sin UI nueva; el mapeo
  pasa a ser **4,5 dB de profundidad extra por punto**.
- **La profundidad extra va DESPUÉS de `gain^alpha`, no antes.** Primero se implementó dentro del
  OMLSA (ancla profunda), que medía un poco mejor en ruido — pero **rompía la receta de operación
  validada en el aire** ("Intensidad baja 50-60% + post-filtro alto"): `alpha` también achica la
  profundidad extra (un bin anclado a −30 dB sale a −15 dB con alpha=0.5), así que había que subir
  la Intensidad para domar el soplido, y al subirla se lleva voz. Reportado en el aire a las pocas
  horas: *"para reducir el ruido o soplido necesito llegar a 0.7 al menos"*. Medido con piso 0.15 y
  post 3: con la profundidad después de alpha, Intensidad **0.4** da −26.3 dB de ruido; antes hacía
  falta **0.7** para llegar a −27.7 dB. **Regla: las etapas que el usuario calibra como
  independientes deben serlo en el código** — si una entra antes de un exponente global, deja de
  serlo en silencio. Test de regresión en `test_noise_vad` (la profundidad extra a alpha 0.5 debe
  ser ≈ la de alpha 1.0).
- **Anti-gorgojeo automático gateado por el VAD de frame**, sin controles nuevos: el suavizado de
  `p_speech` sube hasta `_PS_SMOOTH_QUIET=0.95` y se agrega un EMA de la ganancia final
  (`_GAIN_EMA_QUIET=0.75`), ambos escalados por `(1−voice_prob)` → con voz (vp→1) se desactivan
  solos y no tocan el ataque. `_gain_out_prev` es estado por-bin: reseteado en `reset()` y
  `clear_profile()` (invariante 9).
- Medido (ruido de banda fluctuante ±6 dB, MCRA, receta Intensidad 0.55 + Post 6; `std_dB` =
  fluctuación temporal por bin, `kurt_r` = razón de kurtosis salida/entrada, la métrica objetiva
  de ruido musical): **std 18.0 → 7.7 dB** (el ruido crudo fluctúa 6.4), **kurtosis 4.11 → 2.44**,
  **+3.7 dB de voz**, **S/N de salida 9.7 → 20.3 dB**, ataque de voz 30 → 50 ms. Sin post-filtro
  (defaults) el anti-gorgojeo solo: kurtosis 2.52 → 1.77. CPU: el cancelador BAJÓ ~5 µs/frame (se
  fue el `np.power`).
- **OJO con los presets de fábrica:** el significado numérico del slider cambió (ahora suprime más
  a igual valor). Quedan sin tocar a propósito — hay que re-validarlos en el aire.
- **Invariante reforzado (3ra vez que muerde el mismo patrón):** el `np.maximum` posterior al
  suavizado en frecuencia debe clampear con **el ancla**, no con `_eff_floor`. Clampear con el piso
  normal devuelve los bins suprimidos al piso y anula silenciosamente toda la supresión extra. Pasó
  incluso en el prototipo de esta misma investigación: las primeras cifras del ancla profunda eran
  en realidad "post-filtro apagado". Test de regresión en `test_noise_vad` (post 6 debe suprimir
  ≥6 dB más que post 0).
- **Al testear el suavizado de `p_speech` hay que hacerlo CON VOZ**: sin voz el gate automático lo
  domina y tapa la diferencia del slider (el test viejo comparaba con solo ruido y quedó sin
  sentido — reformulado, mide el slider con voz y el automático sin voz).

**Excitador armónico reescrito** (misma investigación, **pendiente de validación en el aire**):

- **No estaba generando armónicos.** `tanh(d·h) − h` vale, para señal chica, `(d−1)·h`: un realce
  de agudos **lineal**. Medido en v1.9.1 con los defaults (drive 2, mix 0.3): **+1.79 dB** de
  ganancia plana sobre 1 kHz, 3er armónico **58 dB abajo** (inaudible), y el realce comprimía
  ~0.6 dB con nivel alto → brillo que sube y baja con la señal. Buena parte del carácter metálico
  venía de ahí. Además levantaba el ruido residual **+2.07 dB** siempre (corre último, sin gate).
- Ahora: banda 1–3.5 kHz → `tanh(d·u)/d − u` sobre la entrada **normalizada a nivel fijo**
  (`_REF_RMS`, RMS con memoria) → se le resta el **componente lineal por proyección** (dividir por
  `drive` no alcanza: a nivel alto el residuo todavía tiene fundamental y atenuaba 2.3 dB) → LPF
  7 kHz. Medido: fuga lineal **±0.02 dB a cualquier nivel**, H3 real (−40 dB a drive 2, −32 dB a
  drive 5), **independiente del nivel de entrada** (H3 = −32.0 dB a −40/−25/−10 dBFS).
- **Gate por VAD desde el pipeline** (`set_voice_gate`, suavizado ~30 ms): con cancelador + perfil
  solo actúa con voz → el ruido de fondo pasa de +2.07 a **0.00 dB**. Sin cancelador, gate=1.0
  (el vp no se actualiza — invariante 2). CPU +23 µs/frame (+0.23% de un core).
- `drive` pasa a controlar **cantidad y orden** de armónicos (antes no controlaba nada audible) y
  `mix` la cantidad mezclada. **Los presets viejos suenan distinto**: lo audible antes era el
  realce de agudos. Manual ES+EN con nota de migración ("si extrañás ese brillo plano, eso es EQ").
- Normalizar la **salida** de la no linealidad (en vez de la entrada) deja a `drive` sin efecto
  — probado y descartado, queda anotado para no repetirlo.

**Fix del Preview ("escuchar ruido eliminado")** — reportado por el usuario en la primera prueba en
el aire del rediseño: "se escucha mucho la voz y no sólo el ruido". La matemática del preview está
bien (`(1−gain)·spec`: si suena voz, es que se está quitando voz), y medido, el rediseño quita
**menos** voz que v1.9.1 (−6.6 vs −5.4 dB con post 3). Dos causas reales:
- **La cadena de coloreo posterior corría también en preview.** El material de diagnóstico pasaba
  por squelch, nivelador de voz, EQ de presencia/cuerpo y excitador — **las cuatro se disparan
  justo cuando hay voz**, así que un resto de voz apenas audible salía nivelado (hasta +20 dB),
  realzado en 1.5 kHz y, desde el excitador nuevo, con armónicos reales (su gate por VAD **abre**
  con voz). El rediseño del excitador empeoró esto sin querer. Ahora `_preview_mode` en el pipeline
  saltea esas cuatro etapas; se conservan el pasabanda de salida y el limitador. Los manuales
  afirmaban que el preview "no incluye el excitador" — era **falso** desde siempre; corregido.
  Test permanente en `test_pipeline` (cuenta llamadas a las tres etapas con preview on/off — la
  comparación de audio entre dos pipelines NO sirve: el hilo procesador avanza distinto en cada
  corrida y la salida queda desfasada).
- **La Intensidad del preset**: el usuario la subió de 0.55 a 0.9 al reajustar el preset. Medido,
  eso solo quita **1.7 dB más de voz** — el factor más grande de toda la tabla, más que cualquier
  variante del rediseño. Es el comportamiento esperado del control y justo lo que el preview
  existe para mostrar.

**Freeze de MCRA por voz** — la causa de fondo de "escucho voz en el preview en todo el rango de
Intensidad". Midiendo la voz quitada contra la predicción teórica del Wiener quedó claro que **no
seguía la teoría**: se quedaba clavada en −5.4 dB por más que el S/N subiera a 30 dB (donde un
Wiener ideal quitaría −60 dB). Con **perfil estático** sí la seguía (−45.9 dB a S/N 30) → el
culpable era el estimador: **MCRA toma la voz sostenida por ruido** (su ventana de mínimos la
absorbe), λ_d sube hasta el nivel de la voz y el cancelador empieza a restar la voz misma. El
slider "Reactividad del piso" en 500 ms lo acelera.
- Fix: los frames con voz no alimentan λ_d (se marcan contaminados en la cuarentena que ya existía
  para el fading, incluido el marcado retroactivo del onset).
- **El gate es la PERIODICIDAD (autocorrelación), NO el vp** — y esto es lo importante: el vp y la
  peakiness se calculan sobre `snr_post`, que depende de λ_d. Al congelar, el ruido nuevo parece
  señal → sube el vp → **realimenta el freeze**. Medido con gate por vp: ante un salto de ruido de
  +10 dB el vp llegaba a 0.89 y el estimador quedaba congelado el 67% de los frames sin recuperarse
  en 3 s; y como además `p_speech` sube, el post-filtro tampoco suprimía (residuo −7.9 vs −14.6 dB).
  Poner un tope de duración al freeze NO lo arregla (el estimado igual tiene que re-converger). La
  autocorrelación se calcula sobre la forma de onda cruda y no puede realimentarse: medido máx 0.09
  con saltos de hasta +20 dB, contra 0.80 de media con voz a cualquier S/N (98% de los frames sobre
  el umbral). Hold de 300 ms para cubrir los tramos sordos (fricativas).
- Medido (Adaptativo, ventana 500 ms): voz quitada **−5.4 → −23.9 dB** a S/N 20, y la **voz que pasa
  a la salida −3.4 → −0.1 dB**. Seguimiento del ruido, anti-gorgojeo y nivel del residuo: idénticos
  (+10.0 dB ante un salto real, std 7.30, kurt 2.09). Sin costo medible.
- **Regla: un detector que decide congelar un estimador no puede depender de la salida de ese
  estimador.** Si depende, se realimenta y el estado "congelado" se vuelve absorbente.
- Tests en `test_noise_vad` (voz sostenida no contamina, salto de ruido sin voz sí se sigue y no
  dispara el freeze, hold recalculado por hop).

**Ataque de sílaba (voz "limitada")** — reportado en el aire: *"noto alguna distorsión en la voz
cuando subo la intensidad, como que quita ruido pero deja la voz con menos claridad, como limitada"*.
Medido con sílabas de 250 ms contra la voz limpia: **el arranque de cada sílaba salía ~5.8 dB más
atenuado que su meseta** (a Intensidad 0.9) — la envolvente se aplasta y suena a compresor.
- Era mayormente **pre-existente** (v1.9.1: −7.32 dB; el suavizado de `p_speech` agregaba ~0.6 dB).
  La causa es el estimador DD, que tarda 2-3 frames en reaccionar al onset.
- Fix: con voz confirmada por el **VAD rápido** (`voice_prob_sq`, ataque instantáneo, TC 20 ms), los
  bins de `p_speech` que **suben** no se suavizan; los que bajan y todo lo que pasa sin voz siguen
  suavizados. Además el gate del anti-gorgojeo usa `max(voice_prob, voice_prob_sq)` — el lento cae
  entre sílabas, que es justo cuando no hay que suavizar. Medido: ataque **−5.76 → −0.15 dB**, con
  ruido **idéntico** (nivel −19.1 dB, std 7.89, kurt 2.46). LSD sube 0.7-1.0 dB: pasa algo más de
  ruido residual dentro de los frames de voz, que es el trade correcto cuando el síntoma es
  distorsión.
- **El gate por vp_sq es imprescindible**: dejar subir `p_speech` sin gatear arregla el ataque igual
  (−0.21 dB) pero el residuo de ruido empeora **10 dB** (−8.5 vs −19.1) — los bins de ruido que
  parpadean hacia arriba dejan de estabilizarse.
- **Y tiene que dispararse POR FLANCO, no por nivel.** Primero se gateó por nivel de `vp_sq`: pasó
  todos los tests sintéticos (con ruido solo el gate nunca abre) pero en el aire fue una regresión
  inmediata — *"hay mucho ruido de fondo, como de ambiente, y cuando no hay voz es más notorio... la
  cancelación no es mejor ahora y volvió el gorgojeo"*. Motivo: el onset es un transitorio de 2-4
  frames, pero `vp_sq` **se queda alto durante toda la transmisión**, incluidos los huecos entre
  palabras — que es exactamente donde se escucha el fondo. Con el gate por nivel el suavizado quedaba
  desactivado ahí. Medido en una transmisión con huecos: ruido en los huecos **+3.6 dB** y parpadeo
  +1.1 dB. Por flanco (ventana de 4 frames tras el cruce): se recupera casi todo (−27.0 vs −28.0 dB,
  parpadeo 9.54 vs 9.23), el ataque se conserva (−0.05 dB) y el LSD **mejora** (4.67 vs 5.62 a
  Intensidad 0.9) — el ruido extra dentro de los frames con voz también desaparece.
- **Lección de método:** un gate de nivel sobre un VAD con release largo NO es un detector de
  transitorios. Cuando el efecto que se busca es un transitorio (onset), disparar por flanco y acotar
  la ventana. Y los tests de ruido-solo **no** detectan esto: el gate no abre nunca sin voz. Hay que
  medir con una señal que tenga voz **y huecos**, que es donde el usuario escucha el fondo.
- Guard de regresión en `test_noise_vad`: supresión y parpadeo del fondo **en los huecos entre
  palabras**, además del ataque de sílaba.
- El slider "Velocidad de ataque" (`beta_fast`) **no mueve la aguja** en esto (−5.72 vs −5.76):
  actúa sobre el DD por bin, no sobre el suavizado de `p_speech`. No recomendarlo para este síntoma.
- Dos checks viejos de `test_noise_vad` quedaron sin sentido **a propósito** (comparaban el efecto
  del slider Anti-gorgojeo con voz vs sin voz; ahora con voz pesa poco por diseño). Reemplazados por
  umbrales absolutos de parpadeo sin voz + el check de ataque de sílaba.

**Ítem 4 de la investigación — hecho, pendiente de validación en el aire:**

- **Carácter par/impar del excitador** (`exciter_character`, slider en Avanzada Audio): rama par con
  `u²` (sin continua, pasa-altos a 2 kHz) cruzada con la impar. Medido con tono de 1.5 kHz: H2 pasa
  de −110 dB (impar puro) a −20 dB (par puro), y con carácter 1.0 no quedan impares. Las dos ramas
  se igualan en RMS (con memoria entre bloques) para que el control sea un **cruce de timbre y no de
  nivel** — verificado: ±0.02 dB entre carácter 0 y 1.
  **El pasa-altos alto de la rama par no es cosmético:** cualquier no linealidad par genera productos
  de diferencia entre los parciales de la voz, que caen en los graves y suenan a barro. Medido con
  dos tonos (1.4 + 1.9 kHz): el producto de 500 Hz queda a −21 dB con la rama filtrada a 600 Hz,
  −31 dB a 1.2 kHz y −39 dB a 2 kHz. Por eso el filtro va en 2 kHz.
- **Recuperación de graves** (`src/dsp/bass.py` → `BassRestorer`, `bass_enabled`/`bass_amount`,
  checkbox en Módulos + slider en Avanzada Audio): **deriva** el fundamental de los armónicos que
  sobrevivieron al filtro (banda 250–1000 Hz → `band²` → LP 320 Hz → HP 60 Hz, normalizado por el
  RMS de la banda porque el cuadrado es cuadrático). Cada par de armónicos adyacentes produce su
  diferencia, que es f0. Corre **después del pasabanda de salida**: antes, el propio filtro se
  comería lo recuperado. `_REF_GAIN=1.4` calibra el 100% al nivel previo al filtro. CPU 75 µs/frame.
  - **La primera versión era un oscilador en el f0 detectado, y fue un fracaso en el aire**:
    *"quedó muy artificial, y son como demasiados bajos y como que vienen con un poco de delay"*.
    Los tres síntomas salían de lo mismo — el oscilador es independiente de la voz. Medido:
    **coherencia +0.01** con el fundamental original (con entonación real, f0 oscilando 110–140 Hz)
    contra **+0.78** derivándolo; **latencia** de decenas de ms (f0 cacheado cada 3 frames +
    suavizado + envolvente) contra **0 ms**; y con **ruido solo** el oscilador agregaba **+3.3 dB**
    bajo 200 Hz (la autocorrelación se dispara con cualquier cosa periódica) contra **−19.1 dB**.
    Como no hay armónicos de donde derivar sin voz, el módulo nuevo no necesita VAD, ni umbral de
    confianza, ni envolvente, ni depender del cancelador.
  - **Trampa de medición que casi lo tapa:** el primer test de coherencia usaba una voz de f0
    CONSTANTE y le pasaba al oscilador el f0 exacto — su mejor caso posible — y daba +0.77, mejor
    que el derivado. Con f0 variable y el f0 real de la autocorrelación se desploma a +0.01.
    **Para evaluar algo que sigue a la voz hay que usar una voz que se mueva** (entonación), y
    alimentarlo con el detector real, no con el valor verdadero.
  - **Segunda trampa, del mismo tipo: NO calibrar niveles con armónicos 1/k.** El primer
    `_REF_GAIN` se ajustó con esa voz, donde el fundamental es el parcial más fuerte. En una voz
    real la fuente glotal cae ~12 dB/oct y domina el **F1 (300–800 Hz)** — que cae justo dentro de
    la banda que se eleva al cuadrado, así que produce mucha más diferencia. Medido con cuatro voces
    realistas (fuente con tilt + formantes): el 100% quedaba **+10 a +13 dB por encima** del
    fundamental natural, y solo +2 dB con la 1/k. Reportado en el aire: *"el efecto es muy fuerte,
    más de 15% es demasiado"*. Con `_REF_GAIN=0.37` el exceso queda en ±1.7 dB y la dispersión
    entre voces es 2.7 dB. El generador de voz del test ahora incluye tilt glótico + formantes.
  - Se evaluó normalizar por el RMS **total** en vez del de la banda: centra mejor la media (−0.9 dB)
    pero la dispersión entre voces se va a **18.2 dB** contra 2.7 — descartado.
  - `NoiseProfiler.pitch_detect` (property que se había agregado para esto) quedó sin uso y se
    eliminó.
- No hizo falta regenerar los presets de fábrica: con el fix de `from_dict` (invariante 10) las
  claves nuevas ausentes toman el default. **Primera vez que ese fix paga.**

**`tests/test_cpu_profile.py` — benchmark de CPU (reescrito, agosto 2026).** Estaba muerto desde que
se removió la arquitectura de IA (importaba `models.deepfilternet`); se reescribió sobre los módulos
actuales en vez de borrarlo, porque el caso del AMD A6 lo hace útil. **No es un test de regresión**:
no está en `run_all.py` y no falla nunca. Da µs por frame de 10 ms y % de un núcleo, por módulo y
para el pipeline completo en tres configuraciones.
- **El pipeline hay que medirlo con `time.process_time()`, no cronometrando `_process()`.** El DSP
  corre en el hilo procesador; `_process()` solo encola, así que cronometrarlo mide la cola y las
  tres configuraciones dan lo mismo. `process_time` cuenta la CPU de todos los hilos e ignora los
  `sleep` que hacen falta para darle aire al procesador. (Primera versión: los tres perfiles daban
  ~780 µs idénticos, y encima el `sleep(0.3)` estaba DENTRO de la ventana de medición.)
- Referencia en el equipo de desarrollo: pipeline mínimo ~195 µs (1.9% de un core), típico
  (adaptativo + post-filtro) ~234 µs (2.3%), todo activado ~391 µs (3.9%).

## Empaquetado multiplataforma — invariantes (lecciones v1.4/v1.5)

La app es Python + PySide6 empaquetada con PyInstaller para Windows y Linux. Los bugs de
empaquetado se descubren en el hardware del usuario, no en CI — anticiparlos:

1. **Plugins agregados a mano al spec: rastrear sus DT_NEEDED.** PyInstaller solo recorre
   dependencias binarias de lo que él mismo recolecta. Al agregar un `.so`/`.dll` a `a.binaries`
   después del `Analysis` (como los plugins de decoración Wayland), verificar con pyelftools
   (está en el venv) que TODAS sus DT_NEEDED estén en el bundle o sean libs del sistema —
   un plugin presente pero sin sus dependencias falla silencioso (dlopen) y el síntoma aparece
   solo en runtime en la máquina del usuario.
2. **Audio en Linux: `libasound` FUERA del bundle, `libportaudio` DENTRO.** No son simétricas y la
   diferencia importa:
   - **`libasound` se excluye** (filtro explícito sobre `a.binaries` en `reductor-linux.spec`). La
     bundleada es la del runner de CI y no puede cargar los plugins ALSA del host (pulse/pipewire/
     default están en otras rutas y versiones), así que la enumeración de PortAudio se queda solo
     con dispositivos `hw:` y los virtuales desaparecen. Excluida, se usa la del sistema — ABI
     estable, presente en cualquier Linux con audio. **No revertir.**
   - **`libportaudio` se bundlea a propósito** (`find_shared_lib` la busca en el sistema del build
     y la agrega a `extra_binaries`): el wheel de `sounddevice` en Linux NO la trae, así que sin
     esto el bundle no tiene backend de audio. La copia bundleada carga la `libasound` **del
     sistema** en runtime, que es lo que hace funcionar la combinación.
   - Este ítem decía que "ambas se excluyen", lo cual era falso desde siempre — el spec nunca hizo
     eso. Detectado revisando el bundle de la v2.0. **La doc describía la intención, no el código.**
3. **Wayland necesita los plugins de decoración** (`wayland-decoration-client`) que los hooks de
   PyInstaller NO recolectan, y `QT_WAYLAND_DECORATION=bradient` (hook `pyi_rth_wayland.py`)
   porque en GNOME Qt elige `adwaita` (requiere libQt6Svg/DBus) y no hace fallback si falla.
4. **Al recortar módulos Qt del bundle** (filtro `sin_basura_qt()`), validar en runtime en AMBAS
   plataformas — las dependencias de plugins (decoraciones, plataformas) no son evidentes desde
   Windows. Antes de recortar, medir qué pesa; después de recortar, smoke test + prueba real.
5. **Validación en hardware real antes de cerrar.** Para features de UI/audio y cualquier cambio
   de empaquetado: smoke test local no alcanza — la verificación final la hace el usuario en su
   equipo (Windows multi-monitor, notebook Ubuntu/Wayland, interfaz USB de radio). No marcar
   terminado ni publicar release sin esa confirmación; dejar registrado en CLAUDE.md qué quedó
   verificado y qué pendiente.

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
| `tests/test_dsp.py` | BandpassFilter, GainLimiter (curva soft-knee, carry entre chunks), LevelMeter |
| `tests/test_pipeline.py` | Latencia y bypass con config default; supresor de impulsos headless (ON suprime y cuenta hits, OFF control negativo — el impulso pasa) |
| `tests/test_presets.py` | `_capture()` cubre DSPConfig/GainConfig, roundtrips, rename/delete, claves ausentes → default de fábrica (invariante 10) |
| `tests/test_noise_vad.py` | VAD del squelch (ruido fluctuante, voz armónica, release AGC), cuarentena MCRA, clamps de fading. **Validar detectores con ruido fluctuante y voz con envolvente — el gaussiano estacionario da falsos OK** |
| `tests/test_integration.py` | Pipeline headless (`start(headless=True)`) con TODOS los módulos activos: warmup MCRA, ciclo squelch, cambios de modo en caliente, cambio de block size con reinicio |
| `tests/test_cpu_profile.py` | **Diagnóstico, no regresión** (fuera de `run_all`): µs/frame y % de un núcleo por módulo y del pipeline completo en 3 configuraciones. Medir el pipeline con `process_time`, no cronometrando `_process()` |
| `tests/test_ui.py` | UI offscreen (`QT_QPA_PLATFORM=offscreen` + `MainWindow`): orden de pestañas (Módulos en pos 1), "Módulos activos" en su pestaña, visibilidad de botones de perfiles por modo estático/MCRA, gating de controles Avanzados por módulo (invariante 2), restauración de checkboxes desde config (invariante 8), aviso proactivo de dispositivos de APIs incompatibles (ACTIVAR deshabilitado + combos marcados). **SliderRow deshabilita los hijos — testear con `row._slider.isEnabled()`, no `row.isEnabled()`** |

## Estado del proyecto

**Fase 1 + Espectro + mejoras DSP completos** — todas las funcionalidades MVP operativas.
**v1.2 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux.
Versión de app 1.2.0 (`main.py`, título de ventana), manual regenerado
(`MANUAL_ReductorRuidoRadio_v1.2.pdf`, gitignoreado — se regenera desde `MANUAL.md`
con markdown2 + **xhtml2pdf** del venv; weasyprint no funciona en Windows, requiere GTK).

Cambios v1.2:
- MCRA: estimación adaptativa de ruido, seleccionable vs. perfil estático en la UI
- Log-MMSE: reemplaza MMSE-STSA en el estimador de ganancia DD (voz más natural)
- Piso MCRA en espectro: línea amarilla se actualiza cada 500ms con el estimado adaptativo
- Piso estático en espectro: la línea amarilla también aparece con perfil estático (aprendido o cargado de settings.json)
- Indicador del limitador de picos: label en tiempo real junto al slider (naranja/rojo cuando activo)
- Pitch enhancement SSB: detección de f0 por autocorrelación + máscara gaussiana de armónicos
- Post-filtro espectral: segunda pasada sobre bins de ruido contra ruido musical residual; rango 0–4, indicador "Reducción extra" en dB
- Squelch de voz: gate binario (mute completo, sin gorgojeo), dual VAD tracker, indicadores Nivel de voz/Gate, umbral en %
- Piso perceptual: indicadores "Piso vocal" y "Activo" (% bins retenidos), rango de boost 0–250%
- Pitch SSB: indicador "Pitch detectado" (f0 en Hz en tiempo real, verde cuando la máscara actúa)
- Squelch: umbral ampliado a 5–100% (el ruido fluctuante de banda puede marcar 50–60% en el VAD)
- EQ de Cuerpo: segunda banda paramétrica (150–800 Hz, Q fijo 0.9) bajo el mismo checkbox de
  presencia — refuerza fundamentales de la voz; `body_freq/body_db` en DSPConfig; PresenceFilter
  reutilizado (clamp de freq bajado a 100 Hz)
- Fix "Restaurar por defecto" (click derecho en sliders): ahora restaura los valores de fábrica
  (`_DSP_DEF`/`_AUDIO_DEF`/`GainConfig()`), no el valor persistido de la sesión anterior
- Controles de Avanzadas se deshabilitan cuando su módulo está desactivado:
  `refresh_enabled_states()` en cada tab, llamado desde `_on_module_toggled` y `reload()`;
  los sub-módulos del cancelador requieren además `noise_enabled`
- Preset activo persistente: `last_preset` en AppConfig/settings.json; la etiqueta muestra
  "(modificado)" si los valores actuales difieren del preset (`PresetManager.matches()`,
  re-evaluado en `showEvent` de PresetsTab); señal `state_changed` → `_schedule_save`
- Fix cambio de tamaño de bloque: `NoiseProfiler.reset(hop)` no redimensionaba `_floor_curve` →
  con piso perceptual activo, shape mismatch al terminar el warmup MCRA → el error handler
  reseteaba el profiler en loop → "nunca termina de calibrar". También `AGC.set_hop()` recalcula
  las constantes de tiempo (quedaban escaladas al bloque viejo)
- Compensación fading HF: freeze MCRA ante cambios ≥5dB + release DD acelerado (checkbox en Avanzada Cancelador)
- AGC Custom: quinto preset con Target/Ganancia máx/Ataque/Release ajustables en "Avanzada Audio"
  (`agc_target_dbfs/agc_max_gain_db/agc_attack_ms/agc_release_ms` en DSPConfig, persistidos en
  settings.json y presets); sliders habilitados solo con el combo AGC en "Custom", todos live
- Reorganización UI: sub-módulos del cancelador indentados en Módulos Activos (pestaña Principal)
- Revisión de bugs pre-release: clamp de pf_boost desalineado con el slider, squelch podía mutear
  permanente con cancelador off, indicadores con estado viejo tras borrar perfil, beta_release de
  fading aplicando en modo static (ver "Invariantes a mantener")

**v1.3 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux (primeros
con el nombre `RadioNoiseKiller`). Versión de app 1.3.0, manual `MANUAL_RadioNoiseKiller_v1.3.pdf`.

Cambios v1.3:
- Renombre de la app a **RadioNoiseKiller** (nombre final, igual al repo): título de ventana,
  `setApplicationName`, `name=` en ambos specs (exe/bundle pasan de `ReductorRuidoRadio` a
  `RadioNoiseKiller`), artifact del workflow Linux, manual y README. El PDF pasa a llamarse
  `MANUAL_RadioNoiseKiller_vX.Y.pdf`. La carpeta del proyecto local sigue siendo
  `Reductor_Ruido_Radio` (no se renombra el working dir).
- Fading HF calibrable: sliders "Sensibilidad fading" (2–10 dB) y "Duración del freeze" (100–500 ms)
  en Avanzada Cancelador (`noise_fading_change_db/noise_fading_freeze_ms` en DSPConfig, persistidos
  en settings.json y presets); checkbox movido de Avanzada Cancelador a Módulos Activos como
  sub-módulo del cancelador; el indicador FADE/ok queda en Avanzada Cancelador
- Fix squelch + AGC (dos partes, automático, sin controles nuevos):
  1. **Compensación AGC**: el release del AGC tras la voz amplificaba el ruido hasta el target y el
     VAD de energía lo tomaba por voz — el gate no cerraba. El pipeline pasa `AGC.gain_lin` al
     profiler cada frame (`set_agc_gain`) y los trackers de energía descuentan `ganancia²`.
  2. **Confirmación espectral del VAD**: el tracker de energía satura con ratio 2:1 (3 dB) — el
     ruido de banda fluctuante marcaba 100% de voz aunque no subiera de nivel. `vp_raw` se multiplica
     por `max(conf_peakiness, conf_periodicidad)`:
     - *Peakiness*: `mean(top 5% snr_post) / mean(snr_post)` — invariante al nivel (una ráfaga plana
       eleva todos los bins por igual). Ruido exponencial ≈ 4-5; voz (armónicos) 8-18. Mapeo 5.5→9.5.
     - *Periodicidad*: confianza de la autocorrelación (`_pitch_autocorr()`, refactor de
       `_detect_pitch` que ahora corre SIEMPRE, una vez por frame, compartida con pitch enhance).
       Independiente del estimador — cubre voz sostenida cuando la ventana de mínimos de MCRA (800ms)
       absorbió los armónicos y la peakiness se aplana. Mapeo 0.25→0.45.
     La confianza tiene ataque instantáneo y release ~100ms (`_VAD_CONF_RELEASE=0.90`) para cubrir
     valles entre sílabas. Verificado en simulación: ruido fluctuante ±6dB vp=0.00 (antes 1.00),
     voz clara gate abierto 100% (umbral 30% + hold 500ms), release AGC vp=0.00.
- Fix VAD saturado: `vp_raw > vp` estricto hacía oscilar voice_prob_sq 1.0/0.6 por frame con voz
  plena (ambos saturados en 1.0 → el else aplicaba release). Con umbral de squelch >60% el gate
  parpadearía. Fix: `>=` en ambos trackers (lento y rápido).
- Cierre progresivo del squelch (anti "cola de squelch"): durante la retención, ganancia plena en la
  primera mitad del hold (las pausas entre palabras no se atenúan) y fade lineal en la segunda mitad
  hasta el mute — antes el ruido pasaba a pleno volumen todo el hold y cortaba de golpe. Rampa por
  frame (`_sq_gain_prev`) para reaperturas y cierres sin clicks; reemplaza el ramp-out de un frame
  (`_sq_gate_was_open` eliminado). La property `squelch_gate_open` no cambia: gain>0 ⇔ vp≥umbral o
  hold>0, mismas condiciones.
- Cuarentena MCRA (look-behind, sin latencia de audio): `λ_d` se actualiza con el frame de hace
  `_MCRA_QUAR_FRAMES=3` frames (30ms), y solo si ningún frame posterior detectó fade/impulso mientras
  estaba en cola (`_mcra_feed` → deque `[power, contaminado]`). Al detectar un fade, los frames aún
  encolados se marcan retroactivamente — el onset (que la detección ve 1-2 frames tarde por el OLA)
  nunca contamina el estimado. El freeze viejo dentro de `_mcra_update` se eliminó: su semántica vive
  ahora en los flags de la cuarentena (frames encolados con `_fading_active=True` se descartan al
  salir). Durante el warmup se consume igual (el freeze nunca aplicó en warmup). La cuarentena corre
  siempre en modo MCRA (con fading comp OFF no hay flags — es solo un lag de 30ms del estimador,
  inaudible). `_reset_mcra()` limpia la cola (cubre set_mode/reset/clear_profile y cambios de hop).
  Verificado: drift de λ_d tras fade de −14dB: 0.015 dB con comp ON vs 6.5 dB sin protección;
  impulso aislado +20dB: 0.000 dB; adaptación a subidas lentas intacta (+6.1 dB seguidos de +6 reales).
- Fix gorgojeo con fading comp sin fading: el release acelerado (β=0.45) aplicaba siempre que el
  checkbox estuviera activo; en bandas ruidosas sin QSB (40m local) los falsos positivos del
  detector de bins subían casi instantáneo → gorgojeo extra. Ahora condicionado a `_fading_active`
  (invariante 6: las features condicionadas a un modo deben chequear el modo en TODOS sus efectos).
- Tests permanentes nuevos: `test_noise_vad.py` (VAD + cuarentena + fading) y `test_integration.py`
  (pipeline headless todo-activado; usa `pipeline.start(headless=True)`, que omite el AudioStream).
  El test de integración destapó que el constructor del pipeline no honraba toda la config
  (`noise_mode`, `agc_preset`, `noise_alpha/floor` y los enables de blanker/cancelador/presencia
  quedaban hardcodeados o sin aplicar — la UI lo tapaba vía `_apply_loaded_config`). Corregido:
  el constructor ahora inicializa todo desde config; un `ProcessingPipeline(cfg)` recién construido
  se comporta según su config sin pasos extra.
- Limitador de picos con rodilla suave: antes era brickwall ∞:1 con rodilla dura y release 100ms —
  aplastaba los picos de voz de golpe y el envelope "agachaba" los ~150ms siguientes (ducking
  audible). Ahora: curva cuadrática en dominio dB con rodilla de 6 dB centrada en el límite
  (`_KNEE_DB`; passthrough hasta límite−3dB, techo plano en límite+3dB, la salida nunca supera el
  límite) y release 50ms (`_RELEASE_S`). Ambos son constantes de clase en `gain.py` pensadas para
  ajuste de escucha en código, sin controles UI. Fix incluido: el carry del envelope entre chunks
  multiplicaba por 1/coef en vez de coef (inflaba el envelope ~0.04% por borde → limitaba de más);
  ahora procesado por chunks == entero, bit a bit.

**v1.4 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux.
Versión de app 1.4.0, manual `MANUAL_RadioNoiseKiller_v1.4.pdf` (30 págs; el script
markdown2+xhtml2pdf se reescribe en el scratchpad de la sesión cuando hace falta — no está versionado).

Cambios v1.4:
- Optimización de CPU para equipos débiles (reportado 100% en AMD A6, 2 cores): BLAS a 1 thread
  (env vars en `main.py` antes de importar numpy — el busy-waiting de OpenBLAS aparecía como CPU
  alto constante), autocorrelación del pitch cada 3 frames con cache, fast path del limitador que
  evita la curva en dB cuando el frame no llega a la rodilla. **Validado en el AMD A6 real: de 100%
  a <50% promedio.**
- Fixes de empaquetado Linux: excluir `libasound` del bundle (dispositivos virtuales ALSA) y
  preferir la `libportaudio` del sistema (backend Pulse, PCMs virtuales); build de Linux en CI solo
  en tags `v*`.
- Identificador de compilación en el título de la ventana (`buildinfo.BUILD_ID`).
- Presets de fábrica versionados en `Presets/` (5 perfiles JSON: AM local, AM SW ruido
  medio/alto con fading, SSB adaptativo/estático).
- Fix pantallas bajas (reportado en notebook Ubuntu 1366x768): la pestaña Principal ahora vive en un
  QScrollArea (no fuerza la altura mínima de la ventana) y `_restore_or_center` dimensiona la ventana
  a `min(contenido, pantalla-60)` — si no entra, aparece scroll pero la app siempre cabe. La posición
  guardada se clampea dentro de la pantalla actual (cambios de monitor/resolución). Nota Wayland:
  `move()` puede ser ignorado por el compositor — la posición persistida puede no restaurarse ahí.
- Nivelador de voz (`voice_leveler_enabled`, sub-módulo del cancelador en Módulos Activos): segundo
  AGC (`_agc_voice`) post-cancelador/post-squelch, gateado por el VAD — `set_hold(voice_prob <
  _LEVELER_VP_THR=0.30)` por frame: solo adapta con voz presente, con ruido/silencio la ganancia
  queda congelada (no persigue al ruido residual — ese era el riesgo de compensar por
  reduction_db/SNR). Params fijos: target −20 dBFS, max +12 dB, ataque 80ms, release 1500ms.
  Requiere cancelador activo + perfil (invariante 2: el vp no se actualiza sin cancelador).
  `set_hop` en `start()` (invariante 9). Persistido en settings.json y presets.
  Único control expuesto (decisión del usuario, para no sumar controles): slider "Ganancia máxima"
  0–20 dB (default 12) en Avanzada Cancelador → `voice_leveler_max_db` (el clamp del setter del
  pipeline es 0–20 == slider; el clamp interno del AGC es 0–60, más ancho — por eso clampeamos en
  `set_voice_leveler_max_db`). Indicador "Nivelador de voz: +X dB" junto al del limitador en la
  pestaña Principal (verde cuando compensa, actualizado en `_tick_levels`).
- Indicador S/N en la pestaña Espectro: `NoiseProfiler.snr_db` — mean_sig/mean(λ_d) en dB con
  suavizado asimétrico (ataque ~100ms, decay ~1s): lee los picos silábicos sobre el piso, que es el
  S/N que espera un operador (un EMA simétrico promedia los valles entre sílabas y marca ~4 dB con
  voz clara). Sobreestima ~1.5 dB por el bias de min-tracking del estimador — aceptable como
  indicador comparativo. Label en la barra del espectro, actualizado en `_tick_levels`; "—" sin
  perfil o sin stream.
- Fix zoom del espectro al arrancar: los sliders Máx X/Y restauraban su posición desde
  `WindowConfig`, pero `setValue()` corre antes del `connect()` en `_slider_row` → el handler no se
  dispara y el `SpectrumWidget` quedaba con defaults hasta tocar los sliders. Fix: push explícito de
  `set_db_max`/`set_max_freq_hz` tras construir los sliders. Patrón a vigilar: **todo widget cuyo
  valor inicial se setea antes de conectar la señal necesita aplicar ese valor a mano al destino**
  (mismo perfil que el bug de `_update_label` diferido en SliderRow).
- "Aprender ruido" sin saturación: al iniciar el aprendizaje estático, (1) el AGC se congela
  (`AGC.set_hold(True)` — sin hold, el AGC amplifica el ruido de banda hasta el target y el perfil
  captura un barrido de niveles en vez de un nivel estable) y (2) el monitoreo se atenúa −12 dB
  (`_LEARN_DUCK_GAIN=0.25` en pipeline, rampa por frame sin clicks — el duck va DESPUÉS del profiler:
  el aprendizaje ve la señal a nivel pleno). Ambos se liberan al terminar/cancelar el aprendizaje
  (el flag se evalúa por frame desde `noise_profiler.is_learning`) y en `start()`.

### Visualizador de espectro — decisiones de implementación

**Captura de spec_pre en pipeline:** `spec_pre_frames` se llena después del bandpass+ANF y antes del
cancelador de ruido. Así la curva "Entrada" muestra exactamente lo que ve el Wiener, con el mismo
ancho de banda que la curva "Salida" — evita que la entrada aparezca más alta que la salida.

**Piso de ruido (línea amarilla):** se toma un snapshot de `_ema_pre` al llamar `stop_floor_learning()`,
no un acumulado. Con ALPHA=0.35 y 5 segundos el EMA está completamente convergido.
Además, en modo estático `_update_noise_db()` (timer 500ms) dibuja la curva desde
`get_noise_floor_data()` cuando `_db_floor is None` — cubre el caso de perfil cargado desde
settings.json o reinicio del stream (que limpia el widget en `start()`). La condición `is None`
evita re-interpolar en cada tick y no pisa el snapshot del aprendizaje.

**GIL y CPU:** el timer corre a 15 fps (67ms). `_tick()` devuelve inmediatamente si `isVisible()` es
False (tab no activo). Las curvas se dibujan con `QPolygonF` + `drawPolyline`/`drawPolygon` en lugar de
N llamadas `lineTo()` sobre `QPainterPath`, eliminando la contención de GIL con el hilo de audio.

**WindowConfig:** `spectrum_db_max` y `spectrum_max_freq_hz` se persisten en `settings.json`
bajo la clave `"window"` junto con la posición de la ventana.

**v1.5 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux.
Versión de app 1.5.0. **Manual bilingüe**: `MANUAL.md` (ES) + `MANUAL_EN.md` (EN) → PDFs
`MANUAL_RadioNoiseKiller_v1.5.pdf` y `..._v1.5_EN.pdf` (30 págs c/u). **Al editar MANUAL.md hay
que reflejar el cambio en MANUAL_EN.md** — la traducción es manual, no hay sincronización
automática. Terminología EN alineada con `i18n_en.py`.

Cambios v1.5:
- Recorte de módulos Qt sin uso en ambos specs (−52 MB Windows, −21 MB artifact Linux; ver ítem
  del backlog más abajo — falta validar el bundle Linux en runtime).
- Botón ⟳ para refrescar los dispositivos de audio sin reiniciar la app:
  `rescan_devices()` en `audio/devices.py` (`sd._terminate()` + `sd._initialize()` — PortAudio
  congela la lista al inicializar; NUNCA llamar con un stream abierto). El botón se deshabilita
  durante el procesamiento (`_on_toggle_processing`). El repoblado preserva la selección **por
  nombre** (`_select_device_by_name`) porque los índices PortAudio pueden cambiar tras el rescan;
  las señales de los combos van bloqueadas durante el refill y los handlers se llaman explícitamente
  al final para empujar el índice nuevo al pipeline. `_populate_devices` refactorizado:
  `_fill_device_combos()` compartido entre el populate inicial (señales aún no conectadas) y el
  refresh. MANUAL.md Cap. 1 actualizado. Verificado por el usuario con hardware real (interfaz
  USB conectada/desconectada con la app abierta: aparece y desaparece de los combos con ⟳).
- Internacionalización ES/EN: diccionario propio (`src/i18n.py` con `tr()` + catálogo
  `src/i18n_en.py`) en vez de Qt Linguist — con dos idiomas evita el toolchain .ts/.qm y los
  datas extra en los specs; el texto fuente español es la clave y una clave ausente devuelve
  identidad (nunca rompe). `language` en AppConfig/settings.json; `set_language()` se llama UNA
  vez en `MainWindow.__init__` tras `config.load()` y ANTES de `_build_ui()` — cambiar idioma
  requiere reinicio (no hay retraducción en vivo). Combo "Idioma:" en el grupo Control.
  ~250 strings envueltos en `tr()`; los textos con valores usan `tr("plantilla {x}").format(...)`
  (NUNCA f-strings en texto traducible — el template debe traducirse antes de formatear).
  Al agregar UI nueva: envolver strings visibles en `tr()` y agregar la clave a `i18n_en.py`;
  el extractor de claves y el verificador de cobertura/placeholders viven en el scratchpad de la
  sesión (extract_keys.py / check_catalog.py — regenerarlos si hace falta, son triviales).
  Verificado offscreen: UI completa en EN sin fugas en español, ES intacto, 6 suites OK.
  El manual sigue solo en español (traducirlo es una decisión aparte).
- Fix posición de ventana en monitores secundarios: el clamp de v1.4 usaba siempre la pantalla
  primaria y una posición guardada en un segundo monitor saltaba al principal al reabrir. Ahora
  la pantalla de referencia es la que contiene el punto guardado (`QApplication.screenAt`);
  monitor desconectado → fallback a primaria. Verificado por el usuario en setup dual-monitor.
  (Nota de testing: las ventanas lanzadas desde la sesión del agente no son enumerables —
  EnumWindows/MainWindowTitle no las ven; la verificación visual de posición/geometría en
  Windows real la tiene que hacer el usuario.)
- Ícono de la app: `Images/RNK_ico.png` (logo del usuario) → `Images/RNK.ico` (Pillow, 7 tamaños)
  embebido en el exe Windows (`icon=` del spec); `app.setWindowIcon()` en `main.py` vía
  `resource_path()` para ventana/taskbar en Windows y Linux (PNG en datas de ambos specs;
  decodifica con el PNG integrado de Qt6Gui — no necesita los plugins de imagen recortados).
- Fix decoraciones Wayland (barra de título ausente en Linux, verificado por el usuario en la
  notebook Ubuntu/GNOME): tres capas de causa. (1) Los hooks de PyInstaller NO recolectan los
  plugins de `wayland-decoration-client` ni `wayland-shell-integration` — las carpetas quedaban
  VACÍAS en el bundle desde el primer build de Linux (v1.2+, verificado descargando el zip de
  v1.4: mismo hueco; todos los builds anteriores corrían sin barra de título bajo Wayland). El
  spec de Linux los agrega a mano a `a.binaries` desde el PySide6 instalado. (2) En GNOME, Qt
  elige la decoración `adwaita`, que requiere `libQt6Svg` (filtrada por el recorte) y NO cae a
  `bradient` si falla la carga ("Could not create decoration from factory!"). (3) Fix final:
  `pyi_rth_wayland.py` fuerza `QT_WAYLAND_DECORATION=bradient` vía setdefault — las DT_NEEDED de
  bradient son idénticas a las del plugin de plataforma (si la app se ve, bradient carga seguro).
  La barra sale con el estilo genérico de Qt; para el look GNOME nativo habría que restaurar
  libQt6Svg (+0.6 MB) y verificar libQt6DBus. Método de diagnóstico que funcionó: comparar
  contenido de bundles (zip release vs artifact) + leer DT_NEEDED de los .so del wheel con
  pyelftools (está en el venv). `libQt6OpenGL` quedó restaurada en el bundle Linux por un
  intento intermedio — bradient usa libGL del sistema, NO libQt6OpenGL; se puede re-recortar
  si se busca achicar más.
- Fix ventana cortada por el borde del monitor: el clamp de restauración solo garantizaba el
  borde superior — con y bajo, el fondo de la app (ACTIVAR/status bar) quedaba fuera del monitor
  y el scroll de Principal no aparecía (para Qt la ventana no era chica; el monitor la recortaba).
  El clamp ahora usa el tamaño real de la ventana: x+ancho / y+alto dentro de la pantalla de
  referencia, con margen estimado del marco (20/50 px — `frameGeometry` no incluye el marco antes
  de `show()`). Verificado por el usuario.

**v1.6 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux.
Versión de app 1.6.0, manuales `MANUAL_RadioNoiseKiller_v1.6.pdf` (ES, 32 págs) y
`..._v1.6_EN.pdf` (EN, 30 págs). Filtro de salida independiente validado por el usuario
en el aire antes del release.

Cambios v1.6:
- Selector de canal de entrada ("Canal:" en Dispositivos de Audio): `input_channel` en
  AudioConfig ("left"/"right"/"mix", persistido). El stream abre SIEMPRE estéreo cuando el
  dispositivo lo permite (`min(2, max_channels)` por dispositivo, consultado en `start()`) y
  `pick_input_channel()` reduce a mono en el callback — el DSP sigue mono, sin costo extra.
  El cambio es EN VIVO: el callback lee `config.audio.input_channel` por bloque (lectura de
  atributo str — atómica, sin lock). Salida dual-mono (`audio_out[:, np.newaxis]` broadcastea
  a todos los canales) — arregla auricular único/fallo de apertura con salida de 1 canal en
  algunos drivers. Con entrada mono el selector no tiene efecto (columna 0 siempre).
  `AudioConfig.channels` queda como campo legado sin uso. Decisión: NO se hace procesamiento
  dual independiente (nivel 2 descartado por el usuario — duplica CPU y UI sin caso de uso).
  Manuales ES+EN actualizados (Cap. 1). Validado por el usuario con la interfaz USB real.
- Filtro de paso de banda de salida independiente de la entrada (checkbox "Salida independiente"
  + 4 sliders en Filtros DSP, Avanzada Audio): `bandpass_out_independent` +
  `bandpass_out_limits` en DSPConfig, persistidos en settings.json y presets. Con la casilla
  apagada la salida sigue a la entrada (comportamiento legado, default). Motivación: dos
  Butterworth orden 4 en cascada con el mismo corte = orden 8 efectivo en el borde — la voz
  llega doblemente apagada; entrada angosta (2.7k, menos soplido al cancelador) + salida ancha
  (3.5-4k) conserva el borde de la voz. DATO CLAVE del análisis: el excitador corre DESPUÉS del
  filtro post (pipeline.py ~828-832: post → EQ → exciter), así que sus armónicos nunca fueron
  recortados — el beneficio real de la independencia es el des-apilado del rolloff en cascada.
  `set_bandpass_limits` NO toca la salida si independiente; `set_bandpass_out_independent`
  re-empuja los límites de la fuente correcta a ambos modos; en `apply_config` va DESPUÉS de
  los límites (orden importa). `refresh_enabled_states`: checkbox requiere post habilitado,
  sliders requieren además la casilla activa. OJO: `SliderRow.set_enabled` deshabilita los
  HIJOS, no el contenedor — testear con `_slider.isEnabled()`, no con `isEnabled()` del row.
- **Fix crítico de la revisión de código pre-release: `BandpassFilter` escribía en el DSPConfig
  COMPARTIDO** (`set_limits`/`set_mode`/`set_order` mutaban `config.bandpass_limits`, `.mode` y
  `.filter_order`). Con el filtro de salida independiente, mover un slider de salida corrompía
  los límites de ENTRADA en config (misma dict compartida entre ambas instancias): al reiniciar
  la app la entrada heredaba los límites de salida, y un cambio de modo AM↔SSB rediseñaba la
  salida con los límites de entrada. Refactor: cada instancia tiene copia PROPIA de
  mode/order/limits y NUNCA escribe en config (la persistencia la maneja el pipeline, que ya
  duplicaba esas escrituras). **Invariante nuevo: los módulos DSP no escriben en config** —
  reciben valores por setter y guardan estado propio; config es del pipeline/UI.
  Lección de testing: el test original tocaba la entrada DESPUÉS de la salida y re-escribía la
  dict corrupta — probar mutaciones cruzadas en AMBOS órdenes.
- Fixes menores de la misma revisión: `_snr_db` no se reseteaba en `reset()`/`set_mode` (S/N
  viejo tras reiniciar stream); indicadores Reducción/Voz y S/N mostraban valores congelados
  con el cancelador desactivado pero con perfil (invariante 5, lado UI — ahora muestran
  "— (desactivado)").
- Reorden de Módulos Activos (pedido del usuario): "Filtro de paso de banda (post)" movido
  a justo antes de "EQ Voz" — refleja el orden real del pipeline (cancelador → squelch →
  post → EQ → excitador). Tablas del Cap. 3 de ambos manuales reordenadas igual.
- Post-filtro espectral: rango de agresividad ampliado 0–4 → **0–10, validado en el aire por el
  usuario** ("estos valores van bien"). Clamp del setter actualizado en sync en cada cambio
  (invariante 1 — este mismo slider ya mordió una vez). En bins de ruido puro la supresión satura
  en el suelo interno de −46 dB (~sin diferencia audible más allá de 5); el rango alto actúa en
  bins intermedios voz/ruido. Etiqueta nueva "muy agresivo" en i18n_en.py.
  **Técnica de operación descubierta por el usuario (documentada en ambos manuales):** bajar la
  Intensidad del cancelador (50–60%) y compensar con post-filtro alto (5–8) da mejor cancelación
  con voz más natural que subir la Intensidad sola — la Intensidad baja no opaca la voz y el
  post-filtro limpia el ruido actuando solo sobre bins que el VAD marca como ruido. Tenerla en
  cuenta como receta recomendada en futuros presets de fábrica.
- Fix indicador "Reducción extra" congelado (reportado por el usuario): `_pf_extra_db` solo se
  recalculaba dentro del bloque `strength > 0` — al bajar la agresividad a 0 el indicador quedaba
  con el último valor medido (invariante 5, otra instancia). Ahora se resetea a 0 en el else del
  frame, cuando no hay bins de ruido, y en `set_post_filter_strength(0)` (cubre el caso con el
  procesamiento detenido).
- Combos Entrada/Salida deshabilitados durante el procesamiento (reportado por el usuario:
  se podían cambiar pero sin efecto — el cambio de dispositivo requiere reinicio del stream).
  Mismo patrón que el botón ⟳ en `_on_toggle_processing`; el combo Canal queda habilitado
  porque sí aplica en vivo. Los combos ya deshabilitados NO deben deshabilitarse en el
  branch de error de `start()` (el disable va después del start exitoso).

**v1.7 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux.
Versión de app 1.7.0, manuales `MANUAL_RadioNoiseKiller_v1.7.pdf` (ES, 28 págs) y
`..._v1.7_EN.pdf` (EN, 27 págs). Nuevo capítulo/sección "Flujo de calibración recomendado" en
ambos manuales con los tips acumulados del usuario. El título de la ventana pasó a armarse en
`_update_window_title()` (versión "v1.7" hardcodeada ahí, no en el `setWindowTitle` del build).

**v1.8 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux.
Versión de app 1.8.0, manuales `MANUAL_RadioNoiseKiller_v1.8.pdf` (ES, 29 págs) y
`..._v1.8_EN.pdf` (EN, 28 págs). Cierra el último ítem del backlog v1.7 (waterfall) y elimina
el AGC Custom. Título de la ventana "v1.8" en `_update_window_title()`.

**v1.8.1 publicada (julio 2026)** — release de patch en GitHub con distribuibles Windows y Linux.
Versión de app 1.8.1, manuales `MANUAL_RadioNoiseKiller_v1.8.1.pdf` (ES, 31 págs) y
`..._v1.8.1_EN.pdf` (EN, 30 págs). Título de la ventana "v1.8.1" en `_update_window_title()`.
Junta los cambios acumulados post-v1.8 (manual con portada/diagrama gráfico/tip de aprender ruido,
aviso proactivo de dispositivos de APIs incompatibles −9993, ajustes de presets de fábrica). El
aviso −9993 quedó **validado en hardware real por el usuario** (cruce WASAPI+WDM-KS: ACTIVAR
deshabilitado + aviso) además de los tests `test_device_combo.py` + `test_ui.py`. Manuales ES+EN
documentan el requisito de misma API en los consejos de dispositivos.

**v1.9.1 publicada (julio 2026)** — release de patch en GitHub con distribuibles Windows y Linux.
Versión de app 1.9.1, manuales `MANUAL_RadioNoiseKiller_v1.9.1.pdf` (ES, 34 págs) y `..._v1.9.1_EN.pdf`
(EN, 32 págs). Título "v1.9.1 by LU6APA". Tanda de refinamientos de UI + mejora del anti-gorgojeo +
"Acerca de", todo validado por el usuario:
- **Anti-gorgojeo mejorado (suavizado temporal de p_speech):** el ruido musical de fondo venía de bins
  cuya clasificación voz/ruido parpadeaba frame a frame; `p_speech` se recalculaba sin suavizado. Nuevo
  EMA por-bin (`_ps_smooth`, ~60% menos varianza del salto de ganancia), **acoplado al slider
  Anti-gorgojeo (β)** — set_smooth deriva `_ps_smooth` de β (0.90→0, 0.99→0.85), así el slider (que
  tenía poco efecto) recupera efecto fuerte sin control nuevo ni cambio de presets. Default de
  `noise_smooth` 0.97 → **0.96** (zona útil 96-98%). `_p_speech_prev` por-bin, reseteado en reset (inv 9).
- **Post-Filtro movido a la pestaña Principal** (bajo Intensidad, los 2 controles más impactantes juntos
  para el usuario casual): slider renombrado "Agresividad"→"Post-Filtro", con **auto-activar** (>0 enciende
  el post-filtro y sincroniza el checkbox de Módulos; 0 lo apaga). Indicador Reducción extra abajo del
  slider. Quitado de Avanzada Cancelador. Intensidad convertido a SliderRow (mismo largo que el resto).
- **Preview reubicado** junto a Reducción extra (refleja la reducción total Intensidad+Post-Filtro);
  manual aclara qué incluye y cómo calibrar solo Intensidad (Post-Filtro en 0 primero).
- **"Acerca de"** (botón ℹ en la barra de estado): diálogo con versión/build, autor **Germán Pagliaroli —
  LU6APA**, link a GitHub; título con "by LU6APA".
- **Alineación de la pestaña Principal:** gating de sliders bandpass por modo AM/SSB (solo el modo activo
  habilitado; `_on_mode_changed` refresca), barra gris en sliders deshabilitados (`sub-page:disabled`),
  combos + VU + botones + Preview alineados al ancho del slider, Latencia a la izquierda, espacio antes de
  ACTIVAR. **Ancho de ventana FIJO (770, alto flexible)**; SliderRow label 160→150 y slider 432→400 para
  cerrar el hueco nombre-slider y permitir el ancho fijo más angosto. Constantes de layout en `main_window`
  (`_COMBO_W`, `_FIELD_W`, `_WINDOW_W`). **Regla UX: campos de ancho fijo con stretch al final; el ancho
  de ventana es fijo.**
- **OJO patrón repetido:** el hook ruff borra un import agregado en un Edit y usado en el siguiente
  (pasó con `DSPConfig` y `QGridLayout` en main_window) — re-agregar en el mismo Edit o después.

**v1.9 publicada (julio 2026)** — release en GitHub con distribuibles Windows y Linux. Versión de
app 1.9.0, manuales `MANUAL_RadioNoiseKiller_v1.9.pdf` (ES, 33 págs) y `..._v1.9_EN.pdf` (EN, 32 págs).
Título de la ventana "v1.9" en `_update_window_title()`. Salto de menor (no patch) por el volumen:
mejora grande del modo Adaptativo para ruido cíclico de onda corta (Reactividad del piso, Refuerzo
en agudos, fading VAD-smart) + latch del indicador FADE + fixes de UI de sliders. Manuales ES+EN
documentan los controles nuevos (Cap. 7: Reactividad del piso, Refuerzo en agudos) y la receta de
ruido cíclico. Presets de fábrica afinados con los parámetros nuevos. **TODO validado en el aire.**

Cambios v1.9 (todos validados por el usuario, en secuencia atacando el fading de ruido cíclico):
- **Reactividad del piso de ruido (ventana MCRA ajustable):** el MCRA seguía el mínimo del ruido en
  una ventana fija de ~800 ms y con ruido cíclico rápido llegaba tarde a las subidas → en la subida
  suprimía de menos (ruido se cuela), al bajar/llegar la voz suprimía de más (se come la voz) →
  vaivén. La ventana `B×M` pasó de constante a ajustable: `M` se recalcula desde `noise_mcra_window_ms`
  (slider 250–800 ms, default 800 = comportamiento previo) y el hop. Ventana corta = el piso reacciona
  rápido. Slider "Reactividad del piso" en Avanzada Cancelador (solo Adaptativo). Recalculo por hop en
  reset (inv 9), clamp == slider (inv 1). Test en test_noise_vad (ventana 250 sigue una subida de
  +14 dB en 38 frames vs 103 con 800).
- **Refuerzo del piso en agudos (over-sustracción HF, rampa logarítmica):** en >3 kHz la energía del
  ruido es baja y el min-tracking queda anclado en mínimos espurios → el piso HF no sube y el siseo se
  cuela. `noise_hf_boost` (slider 0–150%) multiplica el `noise_mag` **efectivo** (no el estimado
  almacenado) por una curva que crece por octava sobre 2.5 kHz: `1 + hf_boost·log2(f/2500)` (cap 2.5
  oct) → más supresión progresiva cuanto más alta la frecuencia, sin tope duro (a diferencia de la
  rampa lineal inicial). Se aplica en `process()` tras obtener `noise_mag`. Combinar con Excitador/
  Presencia para reponer brillo. Slider "Refuerzo en agudos" en Avanzada Cancelador. Curva rebuild
  en reset (inv 9). **Efecto notorio validado.**
- **Detector de fading VAD-smart:** el freeze no distinguía "se desvaneció la señal" de "subió el
  ruido" (ambos son cambios de energía) y congelaba en los dos → ante ruido que sube, congelar es lo
  contrario de lo que hace falta. Ahora el freeze se **gatea por el VAD** (`voice_prob` del frame
  anterior ≥ `_FADING_VP_THR=0.40`): desvanecimiento de señal (voz presente) congela como antes;
  subida/bajada de ruido de banda ancha (vp bajo) NO congela → el estimador SIGUE el ruido. Coincide
  con la intención original del feature. Automático, sin control nuevo. **Destapó** que la deriva ~1 dB
  del nivelador con ruido de banda ya existía con fading OFF (default): el freeze viejo la enmascaraba
  (congelaba λ_d → snr_post plano → peakiness baja → vp bajo); el check de test_integration se aflojó
  0.5 → 1.5 dB con esa explicación. Tests 5a (ruido sin voz → no congela) y 5b (voz + fade → sí congela).
  **Regla: la lógica del fading debe distinguir señal de ruido por el VAD, no solo por energía.**
- **Latch del indicador FADE:** el freeze dura ~200 ms pero el timer de stats de la UI refresca cada
  500 ms → el poll se perdía la ventana y FADE parpadeaba/no aparecía. `pop_fading_active()` (read+reset
  del latch `_fading_latch`, sin lock — inv 7) reporta a la UI si hubo freeze desde el último poll,
  aunque ya haya terminado. **Validado (a 500 ms de freeze se ve la duración; enciende más seguido).**
- **Fixes de UI de sliders (SliderRow):** (1) `_note` con `setWordWrap(True)` — una nota larga
  estiraba la fila y recortaba el slider; ahora fluye a segundo renglón. (2) Slider de **largo fijo**
  (`setFixedWidth(432)`, sin stretch) + valor alineado a la izquierda pegado al slider + stretch al
  final → nombre/slider/valor juntos a la izquierda, espacio libre a la derecha. (3) `label_width`
  140→160 y nombres nuevos acortados ("Reactividad del piso:", "Refuerzo en agudos:") para que no se
  corten. **Regla UX: los sliders son de largo fijo; las notas hacen word-wrap; los nombres largos se
  acortan (el detalle va en la nota).**
- **Presets de fábrica regenerados** para incluir los campos nuevos (`noise_mcra_window_ms`,
  `noise_hf_boost`) — 4ta vez que un campo nuevo dispara "(modificado)" espurio por claves ausentes;
  **pendiente el fix durable en `from_dict` de presets** (que las claves ausentes usen el default, no
  el valor vivo del config) para que deje de repetirse.

**v1.8.2 publicada (julio 2026)** — release de patch en GitHub con distribuibles Windows y Linux.
Versión de app 1.8.2, manuales `MANUAL_RadioNoiseKiller_v1.8.2.pdf` (ES, 32 págs) y
`..._v1.8.2_EN.pdf` (EN, 31 págs). Título de la ventana "v1.8.2" en `_update_window_title()`.
Junta los cambios acumulados post-v1.8.1 (todos validados por el usuario): nombre del perfil de
ruido cargado en la UI, fix del espectro congelado en Bypass, fix del modo Adaptativo al arrancar,
Sensibilidad fading mínimo 1 dB, coordinación de vocabulario UI/manual, botón Mute de salida, y el
grande: **Nivelador de voz con opción de nivelar en continuo (música) + velocidad de respuesta
ajustable** (para fading cíclico y rápido). Presets de fábrica afinados por el usuario con los
parámetros nuevos.
- **Bug destapado en el release (registrado): presets de fábrica sin las claves nuevas → "(modificado)"
  espurio.** Los presets viejos no tenían `voice_leveler_gate_voice/release_ms`; al cargar uno en un
  config con un valor no-default para esas claves (p. ej. `settings.json` de una sesión con música,
  gate=False), la clave AUSENTE heredaba ese valor en vez del default → no coincidía con el snapshot
  normalizado (que parte de un `AppConfig` limpio) → "(modificado)" permanente. **Regla reforzada: los
  presets de fábrica deben tener TODOS los campos actuales** — al agregar un campo a DSPConfig/_capture,
  regenerar los 8 presets (round-trip por un config limpio). Es la 3ra vez que un campo nuevo muerde
  la comparación config↔preset (ver también el fix de v1.8 con `agc_*`).

Cambios v1.8.2 (los que estaban pendientes post-v1.8.1):
- **Nombre del perfil de ruido cargado visible en la UI** (pedido del usuario: al cargar un perfil
  nombrado no había forma de saber cuál estaba activo). Label verde debajo de los botones
  Guardar/Perfiles: "📁 Perfil cargado: «nombre»". Estado en memoria `_active_noise_profile_name`
  en `main_window.py` — distinto de `config.last_noise_profile` (que persiste el nombre para la
  auto-recarga aunque después se aprenda otro). Se setea al cargar/guardar/auto-cargar; se limpia
  (None) al Aprender un perfil nuevo o Borrar (el perfil activo deja de corresponder al archivo);
  el label se oculta también en MCRA o sin perfil (`show_name` en `_refresh_noise_profile_ui`,
  antes de los early-returns). Clave i18n EN agregada. Test `test_ui.py::test_loaded_profile_name_label`
  (monkeypatch de `noise_has_profile`). **Validado visualmente por el usuario.**
- **Fix: el espectro quedaba congelado en Bypass** (reportado por el usuario). Los frames de
  espectro (`_spec_pre_frames`/`_spec_post_frames`) solo se capturaban en el hilo procesador, que
  en bypass no recibe audio → la pantalla (y la cascada) no se actualizaban. En bypass "lo que se
  escucha" == la señal cruda (entrada == salida), así que `_process` empuja `audio_in.copy()` a
  AMBOS deques en la rama de bypass. `deque.append` es atómico y el hilo procesador no escribe en
  bypass (sin input encolado) → sin carrera nueva. El `SpectrumWidget` concatena y toma los últimos
  `FFT_SIZE` samples, así que el tamaño del bloque del callback no necesita ser `hop`. Test en
  `test_pipeline` (ambos deques poblados y coincidentes en bypass). **Validado por el usuario.**
- **Fix: el arranque no respetaba el modo Adaptativo (MCRA) guardado** (reportado por el usuario:
  cerraba en Adaptativo y abría siempre en estático). Si existía un `last_noise_profile` persistido,
  `_auto_load_noise_profile` lo cargaba y forzaba estático en cada arranque, pisando el modo que
  `_apply_loaded_config` ya había restaurado. Ahora el auto-load chequea el modo PRIMERO: solo carga
  el perfil (y fuerza estático) si el modo guardado ya era estático; en MCRA hace early-return y
  respeta el modo. (El síntoma apareció tras probar la feature del nombre de perfil, que dejó un
  `last_noise_profile` guardado.) Test `test_ui.py::test_auto_load_respects_saved_mode`.
  **Validado por el usuario.**
- **Sensibilidad fading: mínimo bajado de 2 → 1 dB** (reportado por el usuario: 2 dB quedaba corto,
  el QSB suave no disparaba el freeze). Slider 2–10 → 1–10 dB y clamp del setter en sync (invariante
  1: `np.clip(v, 1.0, 10.0)` en `noise_profiler.set_fading_change_db`). **No se baja a 0**: el
  detector usa `change_db >= umbral` con `change_db = |Δ| ≥ 0`, así que 0 dispararía el freeze en
  todos los frames → MCRA nunca actualizaría `λ_d`. Comentarios de rango en `config.py`/`noise_profiler.py`,
  manuales ES+EN (tabla + nota "Bajo (1–4 dB)") y test de clamp en `test_noise_vad` (0.5 → 1.0)
  actualizados. **Validado en el aire por el usuario** (dispara para QSB más suave).
- **Vocabulario de las notas de Avanzadas coordinado con las etiquetas en vivo** (reportado por el
  usuario: la nota de un control decía "bajo/alto" mientras la etiqueta del slider mostraba palabras
  cualitativas). Pasada completa en `advanced_tab.py`: cada nota que usaba "bajo/alto" ahora usa la
  misma palabra que muestra la etiqueta (Velocidad ataque→rápido/suave, Nivelador→fuerte, Excitador
  drive→suave/agresivo, Blanker frame/mini→agresivo/suave, Sensibilidad fading→sensible/selectivo,
  piso boost→fuerte, post-filtro→realineado 1=normal/2=agresivo, EQ Q "estrecho"→"angosto"). Las
  palabras de la etiqueta de Q (`ancho/medio/angosto`) no estaban en `tr()` — envueltas + 3 claves EN
  nuevas (wide/medium/narrow). Espejado en los manuales ES+EN (mismas filas de tabla). Claves i18n ES
  (keys) + traducciones EN en sync. **Regla de UX: la nota de un control usa la misma palabra
  cualitativa que muestra su etiqueta en vivo, no "bajo/alto".**
  **Extensión (reportado post-v2.1): también las UNIDADES.** El tooltip del Piso espectral hablaba
  de "10–15 %" mientras el control muestra `0.05`–`0.30` y el manual usa decimales — el usuario lo
  notó enseguida. Riesgo propio de escribir muchos textos de ayuda de una sentada: se describe el
  parámetro por lo que uno sabe que significa, no por lo que el usuario lee en pantalla. Chequeo
  barato para repetir cuando se toquen los textos: renderizar la etiqueta de cada `SliderRow` en su
  mínimo y su máximo y comparar las unidades que aparecen ahí contra las que cita el tooltip.
  Da falsos positivos legítimos (el post-filtro cita dB por punto, el supresor cita la duración del
  impulso que ataca) — son tres, se revisan a mano.
- **Botón "🔇 Mute" de salida en la pestaña Principal** (pedido del usuario: silenciar la salida sin
  detener el proceso para una prueba corta). Va en la fila de Grabar (grupo Niveles y Ganancia),
  justificado a la derecha; el checkbox "incluir entrada sin procesar" quedó pegado a Grabar y el
  contador REC se movió después del checkbox. **Mute de monitoreo**: `pipeline.set_output_mute()` +
  flag `_muted` (bool atómico, sin lock, igual que `_input_gain`) que zerea SOLO el valor devuelto al
  dispositivo, DESPUÉS de medidores/espectro/grabación — el proceso, la grabación y los VU/espectro
  siguen mostrando la señal (grabar en mute NO graba silencio). Aplicado en ambos returns de
  `_process` (bypass y normal). Botón checkable, habilitado solo con proceso activo (como Grabar),
  rojo "Silenciado" cuando activo, se resetea a off al DETENER. Claves i18n EN. Tests: `test_pipeline`
  (mute silencia salida, espectro vivo) y `test_ui::test_mute_button_gating_and_state`. Manuales ES+EN
  (sección "Mute de salida" bajo Grabación a WAV). **Validado por el usuario.**
- **Nivelador de voz: opción de nivelar en continuo + velocidad de respuesta ajustable** (reportado
  por el usuario: música en onda corta con QSB cíclico y rápido, el nivelador no compensaba). Dos
  cambios sobre el mismo módulo:
  - **Nivelar en continuo (`voice_leveler_gate_voice`, default True):** el nivelador está gateado por
    el VAD del cancelador (`set_hold(voice_prob < THR)`), así que con **música** —sin estructura de
    voz— queda congelado y no compensa. Nueva casilla "Nivelar en continuo (música / sin detección de
    voz)" en Avanzada Audio: marcada → `hold = (gate_voice and vp < THR)` con gate_voice=False → hold
    siempre False → adapta cada frame. Detección automática música/voz descartada (no fiable) → control
    manual.
  - **Velocidad de respuesta (`voice_leveler_release_ms`, default 1500, rango 200–3000 ms):** el release
    del `_agc_voice` estaba fijo en 1500 ms, demasiado lento para fading cíclico rápido (al bajar la
    señal el AGC sube ganancia con el release → pozo audible). Slider "Velocidad de respuesta" en el
    grupo Nivelador; el AGC ya soporta `set_custom_release` (clamp interno 100–8000), el setter del
    pipeline clampea 200–3000 == slider (invariante 1). Rápido (400–600 ms) sigue el QSB cíclico.
  - Ambos en DSPConfig, persistidos en settings.json y presets. Requieren cancelador + nivelador
    (invariante 2). Claves i18n EN; tests en test_ui (casilla) + roundtrip de test_presets.
    **Receta de música + QSB validada en el aire:** continuo + máx ~15 dB + velocidad 400–600 ms.
    Manuales ES+EN actualizados (Cap. 7: dos controles nuevos, tip de música con fading, nota del
    Piso espectral; y la fila de config recomendada pasó de "❌ No usar con música" a "Opcional con
    'Nivelar en continuo'"). **Validado por el usuario.**
  - **Nota de operación (documentada en el manual):** un Piso espectral (`noise_floor`) alto deja pasar
    más señal sin aplanar → transmite más el swing del fading; bajarlo un poco y dejar que el nivelador
    haga el trabajo.
- **`test_integration` desflakeado de verdad** (el check "monitoreo atenuado durante el aprendizaje"
  falló ~50% esta sesión pese al `flat=True` previo). Causa: `rms_pre` se medía sobre 60 frames sin
  cebar la cola async — los primeros frames salen near-zero por el priming del hilo procesador y
  hundían el baseline variablemente (0.0149–0.0217) → ratio learn/pre > 0.6. Fix: warmup de 40 frames
  antes de cada medición (ceba la cola + deja asentar el ramp del duck) + ventanas largas parejas
  (150). Verificado 6/6 estable: rms_pre ~0.025, ratio ~0.29.

Cambios v1.8.1 (los que estaban pendientes post-v1.8):
- **Manual: portada, diagrama gráfico y tip de aprender ruido** (pedidos del usuario):
  - Aclaración en "Perfil estático": correrse un poco en frecuencia a un hueco **sin emisoras**
    (solo ruido) antes de aprender; si entra voz/portadora, queda "horneada" en el perfil y el
    cancelador la resta como ruido → artefactos sobre la voz (ES+EN).
  - **Diagrama del pipeline gráfico**: reemplazado el ASCII por una imagen (cajas coloreadas,
    cancelador destacado, sub-módulos, flechas), embebida en manuales y PDFs. Versiones ES/EN.
  - **Portada del PDF** con el logo `Images/RNK_ico.png` (reescalado), título, subtítulo y versión.
  - **Toolchain del manual ahora versionada en `tools/`** (antes se reescribía en el scratchpad):
    `tools/gen_pipeline_diagram.py` (genera `Images/pipeline_diagram*.png` con PIL) y
    `tools/gen_manual_pdf.py` (markdown2 + xhtml2pdf, agrega portada y resuelve imágenes via
    link_callback). Skill de release actualizado para apuntar a `tools/`. Los PNG del diagrama se
    versionan (los referencia el manual); los PDFs siguen gitignoreados.
- **Combinación de dispositivos incompatible (PaErrorCode -9993)** — reportado por el usuario:
  ciertas salidas (p. ej. "Altavoces WDM", o el Stereo Mix, que solo existen en WDM-KS) dan
  `Error opening stream: illegal combination of I/O devices (-9993)` al Activar. Causa: un stream
  full-duplex de PortAudio exige que entrada y salida sean de la **misma API de host**; combinar
  WASAPI (entrada) + WDM-KS (salida) lo rechaza. La dedup de `list_devices` prefiere WASAPI, pero
  las salidas sin equivalente WASAPI quedan en WDM-KS y se pueden cruzar en los combos.
  - **`audio/devices.py`:** `hostapi_of()`, `duplex_hostapi_mismatch()` (devuelve las dos APIs si
    difieren, o None) y excepción `IncompatibleDevicesError`.
  - **`AudioStream.start()`:** chequeo proactivo ANTES de abrir → lanza `IncompatibleDevicesError`
    con las dos APIs; además traduce el `-9993` residual de `sd.PortAudioError` por si el chequeo
    no lo detectó (red de seguridad).
  - **`pipeline.start()`:** si la apertura del stream falla, hace **rollback** del arranque
    (teardown del hilo procesador + `running=False`) para no quedar a medio camino. El teardown se
    extrajo a `_shutdown_processor_thread()`, compartido con `stop()`.
  - **UI:** `_on_toggle_processing` captura `IncompatibleDevicesError` y muestra un mensaje claro y
    accionable ("elegí ambos dispositivos de la misma API, p. ej. los dos [WASAPI]") en la barra de
    estado + `QMessageBox`, en vez del error críptico.
  - **Test `tests/test_device_combo.py`** (mockea sounddevice, sin hardware): detección del cruce,
    combinación compatible OK, y `AudioStream.start()` lanza antes de tocar PortAudio. En run_all.
  - **Aviso proactivo al seleccionar (hecho):** `MainWindow._check_device_compatibility()` re-evalúa
    en cada cambio de dispositivo (y al arrancar) vía `duplex_hostapi_mismatch`; si las APIs difieren
    **deshabilita ACTIVAR** (con tooltip), marca ambos combos con borde de aviso (`_COMBO_WARN_STYLE`)
    y muestra el motivo en la barra de estado — el usuario ya no puede intentar arrancar una
    combinación inválida. Solo consulta PortAudio (`query_devices`), no abre stream; no corre con el
    stream abierto (los combos están deshabilitados). El flag `_devices_incompatible` evita pisar
    otros mensajes de estado (p. ej. "Perfil cargado") en el arranque. El chequeo del `start()`
    (excepción `IncompatibleDevicesError`) se conserva como red de seguridad. Test en `test_ui.py`
    (`test_incompatible_devices_disable_activate`, monkeypatchea `duplex_hostapi_mismatch`).
  - **Pendiente / futuro:** soporte real de combinaciones cruzadas vía **dos streams separados**
    (InputStream + OutputStream con ring buffer) — más complejo (latencia/sincronía), decisión del
    usuario si vale la pena.
- **Ajustes de presets de fábrica del usuario** (afinados en uso real, se publican tal cual —
  ver [[project_factory_presets]]): `AM Local - RuidoMedio` pasa a perfil estático, intensidad 0.6,
  squelch on, más presencia (1500 Hz / 6 dB) y cuerpo (350 Hz / 3 dB), límite de picos −1.5 dB;
  `AM SW - Ruido Alto y Fading` pasa a modo adaptativo (MCRA).

Cambios v1.8:
- **Cascada / waterfall en la pestaña Espectro** (último ítem del backlog v1.7). Nuevo
  `src/ui/waterfall_widget.py` (`WaterfallWidget`): historia tiempo-frecuencia (~30 s) bajo el
  espectro instantáneo, en un `QSplitter` vertical arrastrable con ejes X (frecuencia) alineados
  (mismos `_ML/_MR/_max_bin/_freq_per_bin` que el espectro). Buffer circular numpy (447 filas @
  ~15 fps), colormap SDR clásico (LUT 256×3, azul→cian→verde→amarillo→rojo) armado por
  interpolación de puntos de control; el pintado mapea dB→color vectorizado y arma un `QImage`
  uint8 escalado (GIL-safe, misma disciplina que el espectro). Eje de tiempo a la izquierda
  (0 s arriba, −30 s abajo), grilla Hz propia abajo (autocontenido para sobrevivir el show/hide).
  - **Fuente conmutable Entrada/Salida** (combo en la fila de controles): `SpectrumWidget._tick`
    empuja la fila dB **cruda** (instantánea, sin EMA — mejor resolución temporal para QSB) de la
    fuente elegida vía `waterfall.push_row()`. Las condiciones de cómputo de `pre`/`post` se
    ampliaron para que la FFT de la fuente corra aunque su curva esté oculta (`set_waterfall_enabled`
    gatea el costo: con la cascada oculta no se computa). Sin doble FFT.
  - **Controles compartidos:** Máx X y Máx Y reescalan ambos gráficos (los handlers empujan a los
    dos widgets). Único control nuevo: casilla "Cascada" + combo de fuente.
  - **Persistencia:** `spectrum_show_waterfall: bool` + `waterfall_source: str` en `WindowConfig`
    (settings.json; fuente inválida → "input"). i18n "Cascada"→"Waterfall". Test en `test_ui.py`
    (splitter con 2 widgets, toggle muestra/oculta + gatea el combo, cambio de fuente persiste,
    push de filas headless sin crash). Verificado visualmente con datos sintéticos (piso + voz +
    heterodino barriendo + QSB): colormap y orientación tiempo/frecuencia correctos.
  - **Los tres ítems "fuera de alcance" se hicieron post-v2.0** (profundidad, colorbar, marcadores
    de heterodino) — ver más abajo.
  - OJO patrón repetido: el hook ruff borró `import WaterfallWidget` y `QSplitter` por agregarse en
    un Edit y usarse en el siguiente — re-agregados. (Ya documentado como riesgo; pasó de nuevo.)
- **AGC Custom eliminado** (decisión del usuario: sumaba 4 sliders y complejidad sin uso real —
  los 3 presets fijos fast/medium/slow cubren los casos). Se quitó el ítem "Custom" del combo AGC,
  el grupo "AGC Personalizado" de Avanzada Audio, los 4 campos `agc_target_dbfs/max_gain_db/
  attack_ms/release_ms` de DSPConfig, sus setters del pipeline (`set_agc_target/...`) y su
  serialización en settings.json y presets. El AGC conserva los `set_custom_*` internos porque el
  **Nivelador de voz** los usa como AGC de parámetros fijos (target −20 / max según slider / 80 /
  1500 ms). Migración: settings.json y presets con `agc_preset="custom"` → `"medium"` al cargar
  (config.py y presets.py). Manuales ES+EN: sección "AGC Personalizado" reemplazada por tabla de
  presets; ref. cruzada del Nivelador de voz depurada.
  - **Bug destapado — comparación de "(modificado)" frágil ante campos eliminados del esquema:**
    tanto `PresetManager.matches()` como el snapshot del título comparaban el **JSON crudo en disco**
    (que retenía las claves `agc_*` viejas) contra `_capture()` nuevo (sin ellas) → nunca coincidían
    → "(modificado)" permanente en todos los presets. Fix durable: **`PresetManager.snapshot(name)`**
    normaliza el preset cargándolo en un `AppConfig` limpio y re-capturándolo, así ambos lados pasan
    por el mismo `_capture()`; claves obsoletas o campos nuevos ausentes ya no generan falsos
    "(modificado)". Lo usan `matches()` y `_refresh_preset_snapshot` en main_window. **Regla nueva:
    comparaciones config↔preset guardado deben normalizar ambos lados por `_capture()`, nunca comparar
    contra el dict crudo de disco.** Los 8 presets de fábrica se regeneraron (drop de claves muertas +
    completados con campos v1.4/v1.6 que predataban). Test `test_ui.py::test_agc_custom_sliders_gated`
    eliminado; `test_integration`/`test_ui` actualizados (usan preset "medium"/"slow").
- **Runner de tests + scripts de conveniencia:** `tests/run_all.py` corre las 7 suites de regresión
  headless en subprocesos aislados (offscreen para UI, exit≠0 si falla). Wrappers en la raíz:
  `run.cmd` (lanza la app, `src/main.py`) y `test.cmd` (corre el runner). Excluidos a propósito
  `test_devices/test_hostapis` (requieren hardware de audio, son diagnósticos).
- **Tests muertos eliminados:** `test_suppression.py` y `test_model.py` (más el bytecode huérfano
  `src/models/`) eran de la arquitectura vieja con modelo IA (DeepFilterNet3 / `ModelConfig` /
  `load_model()`), toda removida hace tiempo — importaban módulos inexistentes y nunca corrían.
- **`test_integration` desflakeado:** el check "monitoreo atenuado durante el aprendizaje" comparaba
  el RMS de dos bloques de ruido con envolvente aleatoria ±4 dB (`noise_frames`); dos sorteos
  independientes difieren varios dB y el ratio del duck (−12 dB) quedaba al borde del umbral 0.6
  (~1 de 4 corridas fallaba). Fix: flag `flat=True` en `noise_frames` (envolvente constante) para
  esos dos feeds → la única diferencia es el duck, ratio estable ~0.33. El drive del test es
  sync+async (`_process` encola y devuelve lo que salió por `_out_queue`), lo que agrega unos frames
  de borde, pero con ruido plano son despreciables. 12/12 corridas OK.
- **Perfil de ruido independiente del filtro** (reportado por el usuario: con perfil estático
  aparecía siseo agudo sin suprimir, sobre todo al reiniciar la app). Causa: el perfil se aprendía
  sobre la señal POST-pasabanda, así que los bins agudos (fuera del pasabanda) quedaban en ~0. Al
  usarlo con un pasabanda más ancho o apagado (o al auto-recargar un perfil nombrado guardado con
  otro filtro tras reiniciar), `snr_post = señal/≈0` → ganancia ≈ 1 → esos bins no se suprimían.
  El `noise_mag` aprendido NO se persiste (settings.json solo guarda `last_noise_profile`, el
  nombre), por eso el síntoma aparecía al reiniciar (se auto-cargaba un perfil nombrado viejo).
  Fix (idea del usuario): **aprender el perfil sobre el espectro COMPLETO** — durante el
  aprendizaje el pipeline alimenta el profiler con el chunk post-AGC PRE-pasabanda/ANF (`prof_in =
  chunk if learning else filtered` en `pipeline._process`), así el `noise_mag` cubre todas las
  frecuencias y el cancelador suprime bien los agudos con cualquier pasabanda (angosto: el filtro
  los quita igual; ancho/off: el perfil los suprime). El pasabanda/ANF igual corren para no congelar
  el estado IIR; su salida se descarta para el aprendizaje. El monitoreo del aprendizaje ya se
  atenúa −12 dB. Decisión del usuario: aprender SIN ANF (ruido de banda ancha crudo; los tonos los
  maneja el ANF en reproducción). Perfiles nombrados viejos (aprendidos post-pasabanda) siguen
  stale hasta re-aprenderlos. Test en test_pipeline (aprende con pasabanda angosto → `noise_mag`
  con energía en agudos → suprime −59 dB con el pasabanda off). **Validado en el aire por el usuario.**
- **Los cambios en pestañas Avanzadas ahora marcan "(modificado)"** (reportado por el usuario:
  "(modificado)" nunca aparecía). Los sliders/checkboxes de las 3 tabs Avanzadas conectan **directo**
  a `pipeline.set_X`, sin pasar por `_schedule_save` de MainWindow → sus cambios no marcaban el preset
  como modificado NI agendaban el guardado de settings.json durante la sesión (solo se guardaban en
  `closeEvent`). Fix: cada tab Avanzada expone una señal `changed` (auto-cableada a todos sus
  `SliderRow.valueChanged` y `QCheckBox.toggled` vía `_wire_change_notifications()` en `advanced_tab.py`),
  que MainWindow conecta a `_schedule_save`. El `_load_values`/`reload` bloquean señales, así que
  cargar un preset no dispara falsos "(modificado)". **Regla de UX: todo control que muta config
  (aunque conecte directo al pipeline) debe notificar a MainWindow para el guardado + indicador.**
  Test en test_ui.py. (Ojo hook ruff: agregar `Signal` al import y su uso en el MISMO Edit, o re-agregar.)
- **"(modificado)" del título instantáneo** (reportado por el usuario: tardaba en desaparecer tras
  sobrescribir, con el audio procesando). Causa probable: `_update_window_title()` hacía una lectura
  de disco (`matches()` lee el JSON del preset) en cada llamada, compitiendo por el hilo de GUI bajo
  carga de audio. Fix: **snapshot en memoria** del preset activo (`_preset_saved_snapshot` +
  `_snapshot_for`, refrescado desde disco solo al cambiar de preset o al forzar tras
  guardar/sobrescribir/renombrar vía `_refresh_title`) y comparación con `PresetManager._capture()`
  en memoria — sin disco. Además `_schedule_save()` ahora llama a `_update_window_title()` en cada
  cambio (antes solo el debounce de 800 ms lo hacía), así el "(modificado)" aparece/desaparece al
  instante. `PresetManager.read()` nuevo (lectura cruda del preset). Test en test_ui.py cubre el
  ciclo modificar→sobrescribir.

Cambios v1.7:
- **Perfiles de ruido nombrados** (backlog v1.7): `NoiseProfileManager` (`src/noise_profiles.py`,
  espejo de PresetManager) guarda/carga/renombra perfiles como JSON en `PerfilesRuido/` (junto
  al exe, gitignoreada). El perfil serializa `noise_mag` + `fft_n` + `learned_frames`.
  `NoiseProfiler.get_profile()/set_profile()` — **set_profile interpola en frecuencia si el
  fft_n de origen ≠ actual** (cambió el block size) y escala la magnitud por `fft_n_dst/fft_n_src`
  (la energía por bin crece con la ventana). `pipeline.set_noise_profile_data()` fuerza modo
  estático (un perfil con nombre solo aplica ahí). UI: botones "💾 Guardar perfil..." (QInputDialog
  + confirmación de reemplazo) y "📁 Perfiles..." (QInputDialog.getItem para cargar), bajo
  Aprender/Borrar, visibles solo en estático. **Auto-recarga**: `last_noise_profile` en AppConfig;
  `_auto_load_noise_profile()` en `__init__` (tras `_apply_loaded_config`) recarga el último y
  devuelve el nombre para el mensaje de inicio. Test permanente `test_noise_profiles.py` (aprender
  headless → guardar → cargar en pipeline nuevo → interpolar 481↔961 bins → rename/delete).
  OJO: los tests headless que aprenden perfil necesitan `time.sleep` tras los `_process` (el hilo
  procesador consume la cola async — mismo detalle que el test de grabación).
- **Grabación a WAV** (backlog v1.7 #1): botón "⏺ Grabar" al pie de Niveles y Ganancia +
  contador REC mm:ss + checkbox "incluir entrada sin procesar" (2do WAV `_entrada` para el
  antes/después; la decisión se fija al INICIAR — `wants_raw` en el recorder — para que
  ambos archivos queden sincronizados). Archivos WAV mono 16-bit 48kHz en `Grabaciones/`
  (junto al exe, gitignoreada), nombre por timestamp con guard anti-colisión (mismo segundo →
  sufijo _2). Arquitectura: `audio/recorder.py` (WavRecorder) con **hilo escritor propio** —
  el hilo DSP solo encola (`feed` = put_nowait; cola llena → descarta frames, nunca traba el
  audio); el escritor cierra los archivos SIEMPRE (finally → header WAV válido incluso tras
  error de disco). Error de disco: el writer marca recording=False y `_tick_levels` lo detecta
  (botón checked + not recording) → cierra UI y muestra el error. Auto-stop al DETENER
  procesamiento (en la UI ANTES de pipeline.stop() para conservar la duración; pipeline.stop()
  también cierra por las dudas). `record_raw_input` en AudioConfig (settings, NO presets).
  Test en test_pipeline (graba 50 frames headless → 2 WAV con 24000 muestras y formato
  correcto). **Bypass durante la grabación** (preguntado por el usuario): el branch de bypass
  de `_process` también alimenta al recorder (feed no-bloqueante, seguro desde el callback) —
  sin eso la grabación quedaba PAUSADA en bypass (el feed vivía solo en el hilo procesador).
  Alternar Bypass grabando = antes/después en el mismo archivo (documentado como feature).
  **Grabación completa validada por el usuario en el aire** (incluido el bypass grabado).
  Nota: al des/activar bypass puede haber unos frames fuera de orden en la grabación (cola del
  procesador drenando mientras el callback ya alimenta) — inaudible, aceptado. OJO hook ruff: al agregar un import en un Edit y su uso en el SIGUIENTE, el hook
  borra el import como no-usado entre ambos — agregar import y uso en el mismo Edit, o re-agregar.
- Técnicas de operación del usuario documentadas en manuales: **calibrar la Intensidad con el
  Preview** (Cap. 7 — subir Intensidad mientras lo eliminado sea solo ruido; donde se filtra
  voz, bajar un paso: máxima cancelación sin tocar la voz) y **activar módulos de a uno**
  (Cap. 3 — escuchar el efecto de cada módulo por separado antes de combinar). Complementan
  la técnica Intensidad baja + post-filtro alto de v1.6. Con 3+ tips acumulados, considerar
  una sección "Flujo de calibración recomendado" en el manual.
- "Refuerzo de pitch SSB" renombrado a **"Refuerzo de pitch de voz"** (checkbox, grupo, i18n,
  manuales): el usuario validó en el aire que también mejora la inteligibilidad en AM — y
  técnicamente es esperable: la demodulación AM preserva la estructura armónica exacta (los
  armónicos quedan en múltiplos enteros de f0, que es lo que asume la máscara), mientras que
  en SSB un BFO desajustado los corre. La cautela original "no fiable en AM" era conservadora;
  el umbral de confianza de la autocorrelación ya protege en condiciones muy ruidosas. La
  recomendación del manual para AM pasó de "No usar" a "Opcional". Los nombres internos
  (`pitch_enhance_*`) no cambian — compatibilidad de settings/presets.
- UX: selector de idioma movido del grupo Control a la **barra de estado** (esquina derecha,
  `addPermanentWidget`, con 🌐 en los ítems y tooltip) — es una preferencia de aplicación que
  se cambia una vez, no un control de operación; ahora es visible desde cualquier pestaña.
  Clave i18n "Idioma:" reemplazada por el tooltip; manuales ES+EN (Cap. 2, sección propia).
- UX: ancho de ventana por defecto 800→960 (a 800 las filas de sliders de Avanzadas quedan
  apretadas) y **el ancho elegido por el usuario se persiste** (`WindowConfig.w`, guardado en
  closeEvent como x/y). Clamp en `_restore_or_center`: [mínimo 800, min(máximo 1100,
  pantalla−40)] — en pantallas ≤840 px de ancho sigue abriendo al mínimo (verificado offscreen
  con la pantalla falsa de 800px; el caso ancho es aritmética directa).
- UX: títulos de los grupos de Avanzadas alineados con los nombres de los checkboxes de
  "Módulos activos" (pedido del usuario — el nombre distinto dificultaba encontrar los
  controles): "Filtros DSP"→"Filtro de paso de banda (pre y post)", "Voz"→"EQ Voz (presencia
  + cuerpo)", "ANF — Filtro de Muesca Espectral"→"ANF — Cancela heterodinos y tonos
  interferentes", "Cancelador de Ruido"→"Cancelador de ruido estacionario", más ajustes de
  mayúsculas (Supresor de impulsos, Excitador armónico). **Regla de UX nueva: todo grupo de
  Avanzadas que corresponda a un módulo usa EXACTAMENTE el nombre base del checkbox.**
  Claves i18n renombradas en sync (verificador de cobertura: 0 faltantes/0 huérfanas);
  referencias de "Ubicación" en manuales ES+EN actualizadas.
- UX: grupo "Nivelador de voz" movido de Avanzada Cancelador a **Avanzada Audio** (junto al AGC
  Personalizado — el usuario reportó que confundía encontrarlo en Cancelador; conceptualmente es
  un AGC). Nuevo indicador "Actividad" dentro del grupo con la ganancia en vivo (mismo dato que
  el de la pestaña Principal, ambos actualizados desde `_tick_levels` y reseteados a "—" al
  detener). El slider sigue requiriendo cancelador + módulo activos (invariante 2); su
  enabled/load viven ahora en `AdvancedAudioTab`. Manuales ES+EN actualizados (Cap. 7).
- UX: **"Módulos activos" movido a una pestaña propia** ("Módulos", 2da posición) para descargar
  la pestaña Principal (quedaba muy cargada). Grupo envuelto en `QScrollArea` igual que Principal
  (pantallas bajas); `_build_modules_tab()` en `main_window.py`; clave i18n "Módulos"→"Modules".
  El orden de pestañas no lo referencia nadie por índice (`_on_tab_changed` usa `idx >= 1`).
- Fix: los botones **Guardar perfil / Perfiles quedaban visibles en modo Adaptativo (MCRA)**
  aunque solo aplican en estático. `_on_noise_mode_changed` ahora los oculta en el branch MCRA
  (invariante 6: chequear el modo en TODOS sus efectos). También más `addSpacing(28)` entre esos
  botones y el slider Intensidad (quedaban pegados).
- **Presets de fábrica "Voz natural" (AM y SSB)**: la receta del usuario (Intensidad 50–60% +
  post-filtro alto 5–8) como preset — `noise_alpha=0.55`, `post_filter_strength=6.0`. Cada
  variante hereda del preset de fábrica de su modo (AM Local / SSB Medio Adaptativo) el resto de
  flags y su bandpass propio. Generados vía `PresetManager.load_into`+`save` (JSON completo con
  campos nuevos). **Validado en el aire por el usuario.**
- **`tests/test_ui.py` permanente** (backlog v1.7): formaliza los tests offscreen de UI que antes
  se hacían a mano cada sesión — la categoría de regresión más frecuente. Ver la tabla de tests.
- **Rolloff del piso perceptual más empinado** (`/6000` → `/2500` en `_build_floor_curve`):
  el usuario reportó que "Profundidad del rolloff" no se notaba entre 0 y −70%. Causa: la rampa
  lineal repartía el efecto sobre 6000 Hz, así que dentro de la banda de voz (SSB 2.7k, AM 4-4.5k)
  la reducción del piso era mínima (−1.3 dB a 4.5k con 55%). Con `/2500` la profundidad plena cae
  cerca del borde de banda → ~2.7× más efecto dentro de banda (−3.5 dB a 4.5k). OJO: en SSB angosto
  con "Inicio del rolloff"=3000 el módulo sigue sin actuar (la banda termina antes de 3000) — la
  nota del slider ahora avisa de bajar el "Inicio" en banda angosta y muestra la atenuación en dB
  (55% ≈ −7 dB). Subir el máximo del slider NO era la solución al problema original (el cuello era la
  pendiente `/6000`, no la profundidad). **Máximo del slider ampliado 0.70 → 0.95** (pedido del
  usuario: en SSB el efecto seguía poco notorio por el ancho de banda angosto — más profundidad da
  margen para combinar con "Inicio" bajo; en SSB con Inicio=1500 el borde de banda pasa de −2.7 dB
  a −5.3 dB). `set_pf_rolloff_depth` clampea a 0.95 (invariante 1: clamp == rango del slider);
  nivel "muy fuerte" agregado a la etiqueta (i18n ES+EN). El techo audible en SSB siempre será
  menor que en AM por el ancho de banda.
- **Default de `anf_depth` bajado de 0.9 → 0.5** (hallazgo del usuario ajustando "SSB - Ruido Alto -
  Perfil Adaptativo"): valores altos de Profundidad del ANF **opacan mucho la voz**; 50% da buen
  balance entre cancelar el tono y no apagar la voz. Cambio en `config.py` (afecta configs nuevas y
  "Restaurar por defecto" vía `_DSP_DEF`; presets y settings.json existentes conservan su valor).
  Nota del slider Profundidad ampliada en la UI (ES+EN) con el aviso. Tip de operación acumulado —
  ya van varios (Intensidad+post-filtro, calibrar con Preview, activar de a uno): al cerrar v1.7,
  considerar la sección "Flujo de calibración recomendado" en el manual (nota vieja del backlog).
- **Preset activo en la barra de título** (pedido del usuario): el título de la ventana muestra el
  preset activo y "(modificado)" si los valores difieren del guardado —
  `RadioNoiseKiller  v1.6  ·  Voz natural - SSB  (modificado)  ·  build XYZ`. `_update_window_title()`
  en `main_window.py` se llama en `_build_ui`, en `preset_loaded`/`state_changed` de PresetsTab, y en
  `_save_settings` (refresca "(modificado)" tras la ráfaga de ediciones, con el debounce de 800ms).
  Reusa la clave i18n `"{name}  (modificado)"` y `PresetManager.matches()`. Test en test_ui.py.

Backlog v1.7 (acordado con el usuario tras la revisión de código de julio 2026):
- ✅ **Grabación a WAV** (hecho, validado en el aire).
- ✅ **Preset de fábrica "Voz natural"** (hecho — AM+SSB; validado en el aire).
- ✅ **Perfiles de ruido nombrados** (hecho, validado con hardware real).
- ✅ **tests/test_ui.py permanente** (hecho).
- ✅ **Waterfall en la pestaña Espectro**: cascada con historia (~30s) además del espectro
  instantáneo — permite VER el QSB, heterodinos intermitentes y QRM (hecho; fuente Entrada/Salida
  conmutable, colormap SDR clásico, splitter arrastrable). **Validado en el aire.**

Pendiente para Fase 2:
- **Agregar el Nivelador de voz al diagrama del pipeline** (`tools/gen_pipeline_diagram.py`, lista
  `STAGES`). Va entre el Squelch y el Filtro de Paso de Banda POST — es la única etapa del pipeline
  real que el diagrama no muestra. Se difirió a propósito en la v2.1: el diagrama lo comparten el
  README y los manuales ES+EN, así que tocarlo obliga a regenerar las dos imágenes y los dos PDFs.
  **Hacerlo junto con el próximo cambio de manual**, no suelto.
- Validar build en Pi real (ARM64 Raspberry Pi OS Bookworm)
- Reducir/optimizar el tamaño total de la app. **Primera pasada hecha y validada en ambas
  plataformas (v1.5):** recorte de módulos Qt sin uso en ambos specs (`QT_EXCLUDES` + filtro
  `sin_basura_qt()`) — Windows dist 218→166 MB, artifact Linux 189→~170 MB (con libQt6OpenGL y
  plugins wayland restaurados tras el fix de decoraciones). Sin recorte posible en scipy (los
  imports de scipy.signal arrastran todo transitivamente — verificado) ni en las dos OpenBLAS
  (ABIs distintas). Pendiente si se quiere más: UPX (no está instalado — el `upx=True` de los
  specs hoy es no-op; ojo falsos positivos de antivirus) y re-recortar libQt6OpenGL en Linux
  (bradient usa libGL del sistema, no la lib de Qt)

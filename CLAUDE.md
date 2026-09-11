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

Parámetros (formulación original de la v1.2; lo que cambió después está debajo del bloque):
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
Lo que se le agregó encima (detalle y mediciones en el historial): la ventana `B×M` es ajustable
(slider "Reactividad del piso", 250–800 ms, v1.9); el umbral δ escala con la ventana (property
`_mcra_delta`, v2.2); el warmup es una ventana completa `B·M` (v2.2); los frames con voz —decidida
por **periodicidad**, no por vp— no alimentan λ_d (v2.0), con hold de 200 ms y umbral ajustable
("Congelar piso con voz", v2.3); cuarentena look-behind de 3 frames (v1.3); freno de caída
opcional ("Freno de bajada", v2.3); squelch de portadora referido al mínimo de la ENTRADA, no a
λ_d (v2.2); y los **armónicos sostenidos se excluyen del piso** (constante `_picos_sostenidos`,
v2.4.1). El indicador S/N usa una recursión paralela sin freno (`_mcra_ld_medido`).

### Pitch enhancement SSB (autocorrelación + máscara armónica)
Feature opcional para señales SSB débiles. Funciona sobre `p_speech` justo antes de OMLSA:
- Buffer rolling de 2048 muestras (~42ms) siempre actualizado, detección lazy.
- `_detect_pitch()`: autocorrelación normalizada vía FFT (4096-point), búsqueda en lag=120..600 (80–400 Hz).
  Retorna f0 solo si el pico de autocorr ≥ 0.30 (umbral de confianza).
- `_harmonic_mask(f0)`: Gaussiana centrada en cada k·f0, clipeada a [0,1]. σ es **proporcional a la
  separación entre armónicos en bins** (`max(1.0, 0.12·f0_bins)`, v2.2) — con σ fija en bins la
  máscara valía ~1 en todo el espectro con bloques chicos y se volvía un piso global de `p_speech`.
- Integración: `p_speech = max(p_speech, hmask · strength)` — solo eleva, nunca baja.
  Esto previene que el cancelador suprima bins de armónicos en señales con SNR muy bajo.
- Hold de 3 frames: el último f0 válido se conserva 3 frames ante gaps de detección.
- **Pide bloque 960 o 1920**: a 480 los armónicos de una voz de 150 Hz caen a 3 bins y no hay
  bin entre armónicos que discriminar. Mismo límite que la exclusión de armónicos del piso.
- Funciona también en AM (la demodulación conserva los armónicos en múltiplos exactos de f0);
  el checkbox se llama "Refuerzo de pitch de voz".
- Sin efecto si f0 no detectado o pitch disabled (passthrough).
- `pitch_enhance_enabled / pitch_enhance_strength` en DSPConfig; checkbox en `MainWindow._build_modules_group()` (sub-módulo indentado bajo el cancelador), slider de sensibilidad en `AdvancedNoiseTab`.

### Post-filtro espectral (ruido musical residual)
Segunda pasada sobre los bins de ruido después de OMLSA+alpha para eliminar el ruido musical
("pitidos fantasma") que el Wiener deja cuando el VAD marcó el bin como ruido pero no lo suprimió
del todo. **Desde la v2.0 resta una cantidad fija de dB** en los bins de ruido:
`gain_post[k] = gain[k] · (10^(−4.5·strength/20))^(1 − p_speech[k])`, tope −60 dB
(`_POST_DB_PER_UNIT`, `_POST_MIN_GAIN`). La fórmula anterior, `gain^(1+strength·(1−p))`, multiplicaba
por (1+s) la fluctuación EN dB del ruido y era la fuente dominante del gorgojeo — no volver a ella.
- Bins de voz pura (`p_speech=1`): sin cambio. Bins de ruido puro (`p_speech=0`): −4,5 dB por punto
  del slider (0–10). Bins intermedios: profundidad proporcional a `1 − p_speech[k]`.
- Aplicado **después** de `gain^alpha` (las etapas que el usuario calibra como independientes deben
  serlo en el código), tras el suavizado en frecuencia, antes de `spec_out = gain·spec`.
- El factor puede hundirse al instante pero sólo **se retira `_POST_RELEASE_DB = 12` dB por frame**
  (v2.2): sin eso, el arranque de cada palabra descargaba ~27 dB en un frame y crujía. No bajarlo sin
  mirar la columna del ataque en el comentario de la constante.
- `post_filter_enabled / post_filter_strength` en DSPConfig; el slider "Post-Filtro" vive en la pestaña
  Principal bajo Intensidad y **auto-activa** el módulo (>0 enciende, 0 apaga); indicador "Reducción
  extra" debajo.
- **IMPORTANTE — no clampear con `_eff_floor` después del post-filtro.** El `np.maximum` final debe usar
  un suelo bajo (`0.005`, −46 dB) para proteger de underflow, NO `_eff_floor`. Clampear con el piso
  espectral (0.10 = −20 dB) devuelve todos los bins suprimidos al nivel del piso y anula silenciosamente
  toda la supresión extra — el slider de agresividad no tiene efecto audible. El `_eff_floor` ya fue
  aplicado antes por OMLSA y no debe re-aplicarse después de una etapa de supresión adicional.

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
6. **Features condicionadas a un modo deben chequear el modo en TODOS sus efectos.** El caso que
   lo enseñó fue la compensación de fading (ya eliminada): su `beta_release` aplicaba en modo
   static aunque la detección sólo corría en MCRA, y al salir del modo el flag de estado quedaba
   pegado en True. La regla sigue valiendo para cualquier feature con estado propio: si depende
   de un modo, chequearlo en todos sus efectos y resetear el estado al salir.
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


## Reglas de método (destiladas del historial)

Las lecciones que más veces mordieron. Cada una tiene su caso concreto en `docs/HISTORIAL_TECNICO.md`.

**Sobre estimadores y detectores (la trampa autorreferencial, SEIS veces):**
1. **Un detector que decide congelar o corregir un estimador no puede tomar su decisión de la salida
   de ese estimador.** Se realimenta y el estado "congelado" se vuelve absorbente. Casos: freeze de
   MCRA por vp, congelar el AGC por VAD, detector de estimado obsoleto, squelch de portadora contra
   λ_d, y el propio gate `S_f/S_min` de MCRA. **Ningún estadístico interno de MCRA puede decir que
   λ_d está obsoleto** — la referencia tiene que venir de afuera (periodicidad, mínimo de la entrada).
2. **Cuando el problema es que un estimador se queda sin datos, mejorar el detector que le corta los
   datos empeora las cosas.** El detector actual funciona *porque se equivoca*.
3. **Cuando un detector nuevo puede equivocarse, elegir la acción cuyo fallo sea benigno** (re-entrar
   en warmup, no levantar el freeze).
4. **Lo que separa un evento de un transitorio es el TIEMPO, no el valor instantáneo**: persistencia
   (ANF 350 ms, picos sostenidos 60 ms, estimado obsoleto 2 s). Y un gate de nivel sobre un VAD con
   release largo no es un detector de transitorios: disparar por flanco y acotar la ventana.

**Sobre medir:**
5. **Antes de implementar algo validado sólo en banco sintético, medirlo sobre las grabaciones
   reales del usuario, a IGUAL NIVEL DE VOZ.** Tres corridas que evitan escribir código: la máscara
   armónica anduvo en banco y dio balance −0,06 dB en el aire.
6. **Toda comparación contra un control existente va en el punto que iguala el costo** (interpolando
   la curva del propio slider), y **el barrido del control tiene que cubrir el punto del rival**.
   Si no, se mide la perilla y no la idea. El baseline contra sí mismo tiene que dar **cero exacto**
   antes de creerle a la métrica.
7. **Para medir el sesgo de un estimador de ruido hace falta ruido CONOCIDO.** Comparar λ_d contra el
   mínimo de su propia ventana está viciado (cambia con el hop y la ventana sin significar nada).
8. **Una diferencia entre dos zonas de UNA grabación no es una propiedad hasta replicarla** (d′ 2,18
   en 10 s → 0,25 en 304 s). Y **confirmar con el usuario QUÉ hay en la grabación** antes de medir:
   cinco detectores automáticos no supieron que era voz continua.
9. **Una señal de test demasiado limpia da el resultado dado vuelta**, en los dos sentidos (falso OK
   y falso MAL). Voz con tilt glotal, formantes, fricativas y entonación; ruido fluctuante; y **un
   guard de un estimador de ruido nunca alimenta señal sin piso de ruido**.
10. **Dos configuraciones se comparan sobre la MISMA señal**; si el generador está dentro de la
    función bajo prueba, no lo están. Y una sola semilla es lotería: promediar varias.
11. **No medir el efecto de algo sobre el audio con el pipeline y su hilo**: replicar la cadena en
    sincrónico. La dispersión entre corridas se come la diferencia y hasta da vuelta el signo.
12. **La señal de diferencia en dB no mide saliencia perceptual**; lo que se escucha es el balance
    voz/fondo. Y una métrica de "supresión" con voz continua cuenta voz comida como mejora.
13. **Un guard nunca toma del default el valor que está probando** (tres veces mudo por eso), y **si
    un guard contradice una medición replicada, sospechar primero de lo que hereda del archivo**
    (hop, sr, duración) cruzando señales y funciones entre bancos.
14. **Al evaluar una separación de fuentes, medir primero el techo con una máscara oráculo**: sin eso
    no se distingue "la idea no sirve" de "el banco está roto".
15. **Al evaluar una mejora incremental, re-medirla DESPUÉS de integrar la anterior**: dos mecanismos
    que comparten detector no suman (la cuarentena retrospectiva pasó de −1,08 a −0,45 dB).
16. **Cuando una búsqueda larga se queda sin ideas, preguntarle al operador qué encontró tocando.**
    El cierre del salto del fondo lo encontró el usuario ajustando presets.
17. **Cuando un control nuevo mueve el ajuste de OTRO en la dirección que predice su mecanismo, vale
    más que un "se nota"** (la Intensidad subió en los 5 presets tras la exclusión de armónicos).
18. **Una hipótesis que lleva a encontrar un bug real no queda validada por eso** (la "curva
    corrupta" nunca ocurrió; el fix de `reset()` vale solo).

**Sobre controles:**
19. **Un control cuyo extremo es casi siempre el mejor es una constante mal puesta**; un slider se
    justifica sólo cuando los dos extremos son defendibles por condición.
20. **Un umbral absoluto en dBFS calibrado contra el entorno de RF de una estación no es portable**:
    default "desactivado" y los presets de fábrica lo llevan apagado. Un umbral relativo necesita
    una referencia que el propio control no perturbe.
21. **Las etapas que el usuario calibra como independientes deben serlo en el código** (la
    profundidad del post-filtro va después de `gain^alpha`).
22. **Un detector de "esto no funciona" tiene que empezar por los estados en los que NO debe
    funcionar** (el bypass dio la firma exacta de un fallo real durante cuatro rondas).
23. **Una nota de operación que nunca se midió puede mandar al usuario al lado equivocado durante
    versiones** (el Piso espectral y el fading decían lo contrario de lo medido).

**Sobre el código y el repo:**
24. **Los módulos DSP no escriben en config**: reciben valores por setter y guardan estado propio.
25. **Todo indicador que sólo pinta `_tick_levels` necesita su reposo en `_reset_live_indicators()`**
    — el `else` del tick no corre cuando el timer se detiene (invariante 5, variante del timer).
26. **El hook ruff borra un import agregado en un Edit y usado en el siguiente**: import y uso en el
    mismo Edit, o re-agregar. Ha pasado cuatro veces.
27. **Texto traducible: `tr("plantilla {x}").format(...)`, nunca f-strings.** Al editar `MANUAL.md`
    reflejar en `MANUAL_EN.md` (traducción manual). Antes de borrar una clave i18n, buscar el texto
    en el código: dos controles pueden compartir etiqueta. Chequeo barato: parsear `i18n_en.py` con
    `ast` y contar claves repetidas. La nota y el tooltip de un control usan las **mismas palabras y
    unidades** que muestra su etiqueta en vivo.
28. **Al commitear con cambios del usuario en el árbol, listar los archivos a mano** (`git add -A`
    coló presets y `errores_dsp.log` dos veces). **Un renombre que sólo cambia mayúsculas necesita
    `git mv` explícito**: Windows no lo ve y el síntoma aparece sólo en Linux.
29. **Verificar que el artefacto contenga lo que debe, no sólo que el build haya terminado** (dos
    releases salieron sin presets). **Una opción de build que depende de una herramienta ausente no
    está desactivada, está esperando.** Leer la anotación del job de CI antes de teorizar.
30. **El ancho de un botón que cambia de texto se calcula con el texto más largo de todos sus
    estados**, y el recorte de un texto con emoji se verifica MIRANDO la app en la plataforma real.
31. **El orden de los tests es parte del test**: un guard que sólo falla con la suite entera es un
    bug real (el guard inerte de `apply_config`). Un fixture no se llama como un dato real del
    usuario.
32. **Grabar sale más barato que inventar la señal**: con un síntoma que sólo aparece en el aire, el
    grabador con canal crudo es la herramienta. Tres bancos sintéticos fallaron con la firma "todas
    las variantes dan lo mismo" antes de que la grabación real destrabara el diagnóstico.
33. **Cuando dos rondas de lectura de código no dan, instrumentar** (`mcra_diag`, `errores_dsp.log`).
    Y cuando el repro no falla, **el dato que sobra en el log es el que discrimina**.

## Descartado — NO reproponer

Cada ítem se probó, se midió o lo decidió el usuario. El bloque con las cifras está en
`docs/HISTORIAL_TECNICO.md` bajo el título que se cita en cursiva. Reproponer uno de éstos sin
leer ese bloque es repetir trabajo que ya costó.

**Cancelador / MCRA (el salto del fondo y la voz que se lleva):**
- **Mejorar el VAD del freeze de MCRA (Silero, autocorrelación mejorada, cualquier detector
  "mejor")**: un detector PERFECTO es el peor de los tres — con voz continua congela siempre y λ_d
  no aprende → *"el umbral del freeze de MCRA pasa a ser ajustable"*.
- **Los doce enfoques del salto del fondo**: freno de caída de ganancia por bin, `beta_fast`,
  ventana de ataque de `p_speech`, bloque más grande, reactividad del piso corta, detector de
  estimado obsoleto + resync, ruido de confort, compresor de salida, freno de subida del piso de
  salida, look-ahead del estimado, freeze partido, freeze por bin → *"el fondo salta cuando el
  ruido de banda sube. DIEZ enfoques descartados"*. Lo que funciona es combinar Freno de bajada +
  Congelar piso con voz + Refuerzo en agudos en 0, por condición.
- **Planitud espectral (SFM) como árbitro** ruido-subió vs voz-arrancó: techo real 0,56, y a S/N
  bajo la voz se aplana → *"DESCARTADO por medición: planitud espectral"*.
- **Reducir el daño del post-filtro a la voz**: cinco caminos (profundidad por S/N del frame, pitch
  más fuerte, bajar `_VAD_THRESHOLD`, protección de consonantes, oráculo) caen sobre la MISMA curva
  que mover el slider → *"el cancelador se lleva 6–8 dB de la banda de voz"*.
- **Corregir λ_d contaminado por voz**: escalarlo (uniforme o por máscara armónica — implementada
  entera y **revertida tras el aire**), alargar la ventana de mínimos, mejorar la velocidad de
  seguimiento, cualquier estadístico interno de MCRA, gate agresivo sin persistencia (**empeora**),
  híbrido con perfil estático, **cuarentena retrospectiva** (−0,45 dB tras la exclusión de
  armónicos, no justifica 200 ms de latencia — decisión del usuario) → *"Post-v2.4 — el cancelador
  se lleva 6,5 dB de voz"*. Lo único que sobrevivió es la exclusión de armónicos sostenidos.
- **Detector de estimado obsoleto** (tras re-sintonizar) y el **botón "recalibrar el piso"**: d' 0,25
  sobre 304 s de control, y el síntoma dejó de aparecer → *"DESCARTADO por medición: el detector
  de estimado obsoleto"*. Si vuelve, el camino es el botón, no un detector.
- **α lento con voz en MCRA** (alimentar λ_d despacio con frames de voz): el gate no distingue
  "subió el ruido" de "hay voz" → *"revisión del MCRA — el hold del freeze y el umbral δ"*.
- **Compensación de fading por energía de frame** (freeze + release DD acelerado): detectaba
  sílabas, y con oráculo perfecto no cambiaba nada con ruido local → *"la compensación de fading
  detectaba sílabas, no fades. ELIMINADA"*. Contra el QSB sirve la velocidad del nivelador.
- **Criba armónica contra el splatter de SSB**: +0,6 dB con vara de 6, estructural (el splatter
  vive en los huecos, donde no hay pitch) → *"criba armónica contra el splatter"*.
- **σ fijo en Hz para la máscara de pitch**: mide un decimal mejor pero es la fórmula equivocada →
  *"la máscara del refuerzo de pitch no discriminaba"*.

**Supresor / AGC / excitador / graves:**
- **Limitador dedicado para los subidones del fading**: peor que el umbral de trama del supresor →
  *"el supresor de impulsos en valores agresivos SÍ ayuda"*. **Bajar el umbral MINI** para
  perseguir ese efecto vuelve a la distorsión de antes de la v2.2 (−8,7 dB con mini en 4).
- **Exigir que el impulso sea breve** en el blanker: no mueve nada y excluye el QRN real.
- **Congelar el AGC cuando no hay voz**: se traba (el VAD ve la señal que el AGC atenúa) → *"techo
  de ruido del AGC"*. **Auto-mute por temporizador**: el techo lo hizo innecesario.
- **Slider para el freno de apertura del techo del AGC**: una punta es siempre peor → constante.
- **Oscilador en el f0 para los graves**: artificial, con delay, suma +3,3 dB con ruido solo → se
  derivan de los armónicos. **Normalizar la salida** (no la entrada) de la no linealidad del
  excitador deja a `drive` sin efecto.

**Controles y UI eliminados o rechazados:**
- **Squelch de voz** (→ Gate de ruido, v2.3), **combo Modo AM/SSB** (→ Pasabanda, v2.3), **AGC
  Custom** (v1.8), **Corrección de tono SSB** (post-v2.2), **presets "Voz natural"** (v2.3),
  slider **"Excluir armónicos del piso"** (→ constante, v2.4.1). No volver a agregarlos.
- **Vista doble de la cascada** (entrada|salida): rompe la alineación del eje X y deja 300 px por
  panel → modo Diferencia.
- **Dos streams para el cruce de APIs WASAPI/WDM-KS**: queda bloqueado con aviso (decisión del
  usuario). **Procesamiento estéreo dual independiente**: duplica CPU y UI sin caso de uso.
- **Detección automática música/voz** para el nivelador: no fiable → casilla manual.
- **Subir los indicadores de 7/8 pt**: el usuario dijo que no hace falta.
- **"Silenciado" recorta en el botón Mute**: NO recorta en la app real; la medición headless usa
  otra fuente. No "arreglarlo".
- **`.github/FUNDING.yml` / GitHub Sponsors** y **PayPal**: no por ahora (Cafecito cubre el caso).

**Build:**
- **UPX**: Defender marca las DLL comprimidas en VirusTotal (el escaneo local da limpio y no sirve
  para estimarlo), +88 MB de RAM, y rechaza el exe y Qt por CFG. Specs en `upx=False` a propósito
  → *"DESCARTADO por medición: UPX"*.
- **Publicar el build ARM64 como asset** sin que alguien lo arranque en una Pi real.

## Estado actual del proyecto

**v2.4.1 publicada (septiembre 2026)** — última release en GitHub, distribuibles Windows y Linux,
manuales `MANUAL_RadioNoiseKiller_v2.4.1.pdf` (ES, 44 págs) y `..._v2.4.1_EN.pdf` (EN, 43 págs),
título "v2.4.1 by LU6APA". Validada en hardware real por el usuario. Cadena de versiones y qué
trajo cada una: tabla al principio de `docs/HISTORIAL_TECNICO.md`.

Lo que define el producto hoy, en una línea cada uno (el detalle está en el historial):
- **Cancelador**: Log-MMSE + OMLSA sobre un piso que viene del perfil estático o de MCRA. En MCRA el
  freeze por voz se decide por **periodicidad** (autocorrelación), nunca por el vp; los frames con
  voz no alimentan λ_d; los **armónicos sostenidos se excluyen del piso** (constante, v2.4.1, pide
  bloque 960/1920); cuarentena de 3 frames; **Freno de bajada** (default 30 = sin freno) y
  **Congelar piso con voz** (30–100 %) como controles por condición.
- **Post-filtro** resta dB fijos en bins de ruido (4,5 dB/punto, retirada frenada a 12 dB/frame),
  **después** de `gain^alpha`. Anti-gorgojeo automático gateado por el VAD.
- **ANF** con persistencia temporal de 350 ms (lo que separa heterodino de armónico es el tiempo).
- **Supresor de impulsos** por contraste local en el tiempo; el umbral de **trama** (2–30) además
  suaviza los subidones del fading; el de **mini** no se baja (vuelve la distorsión).
- **Gate de ruido** por nivel de entrada en dBFS, actúa sobre la salida, atenúa 20 dB, viene
  desactivado (umbral por estación). **AGC** con techo de ruido (cierre instantáneo, apertura a
  0,5 dB/s), también por estación y desactivado en los presets de fábrica.
- **Combo Pasabanda** (8 anchos) en lugar del modo AM/SSB; nivelador de voz con modo continuo;
  excitador con armónicos reales gateado por VAD; recuperación de graves derivada de los armónicos.
- **5 presets de fábrica** en `Presets/`, afinados en el aire (ver [[project_factory_presets]]):
  no se alinean con defaults ni se commitean con `git add -A`.
- **UI**: cascada con modo Diferencia y marcadores de heterodino; Grabar/Bypass/Mute como botones
  de 140 px; tooltips en los 45 sliders; escala 100/125/150 %; i18n ES/EN; "Acerca de" con Cafecito.

### Cambios pendientes de release

_(ninguno — la v2.4.1 es la última y no hay nada acumulado en `main` desde entonces)_

Formato al acumular: una línea por cambio con su estado de validación (`validado en el aire` /
`pendiente de validar`), y el bloque narrativo completo en el historial, sección "En curso". El
skill `release` toma las notas del release de esta lista.

### Pendiente para Fase 2
- Validar build en Pi real (ARM64 Raspberry Pi OS Bookworm)
- Reducir/optimizar el tamaño total de la app. **Primera pasada hecha y validada en ambas
  plataformas (v1.5):** recorte de módulos Qt sin uso en ambos specs (`QT_EXCLUDES` + filtro
  `sin_basura_qt()`) — Windows dist 218→166 MB, artifact Linux 189→~170 MB (con libQt6OpenGL y
  plugins wayland restaurados tras el fix de decoraciones). Sin recorte posible en scipy (los
  imports de scipy.signal arrastran todo transitivamente — verificado) ni en las dos OpenBLAS
  (ABIs distintas). **UPX quedó DESCARTADO por medición** (Defender marca las DLL comprimidas y
  cuesta +88 MB de RAM — ver el historial, "DESCARTADO por medición: UPX"), y los specs pasaron a `upx=False`. Lo
  único que queda si se quiere más: re-recortar libQt6OpenGL en Linux (bradient usa libGL del
  sistema, no la lib de Qt)

## Historial técnico — dónde está el detalle

**`docs/HISTORIAL_TECNICO.md`** tiene el registro completo de cada versión (v1.2 → v2.4.1): qué se
hizo, qué se midió, qué se descartó y por qué, con las cifras y las citas del usuario. Se sacó de
este archivo en septiembre 2026 porque `CLAUDE.md` había superado el límite de 150k caracteres
que Claude Code carga por sesión (estaba en 286k y la mitad quedaba truncada sin aviso).

- **No se importa con `@`** a propósito: volvería a cargar los 267k en cada sesión. Se lee a
  demanda con grep por versión (`v2.2 —`, `Post-v2.3`) o palabra clave (`λ_d`, `oráculo`, `UPX`).
- **Antes de proponer un cambio al cancelador, al MCRA, al supresor o al AGC**, buscar el tema
  ahí: casi todo lo obvio ya se probó y está medido. La lista corta está en "Descartado — no
  reproponer" más arriba.
- **Las notas nuevas van al historial**, en su sección "En curso", con el mismo formato de bloque
  (`**Post-vX.Y: título.** contexto, medición, decisión, test`). En este archivo va sólo la línea
  de resumen en "Cambios pendientes de release", más la entrada en "Descartado" o la regla de
  método si el hilo dejó una. **Este archivo tiene que quedar bajo ~60k caracteres.**

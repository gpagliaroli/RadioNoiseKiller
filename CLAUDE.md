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

### Compensación de fading HF (noise_fading_comp) — ELIMINADA post-v2.2
> Se quitó del código tras medirla (ver el bloque "v2.2 — la compensación de fading
> detectaba sílabas" más abajo). Lo que sigue describe cómo funcionaba, para que quede
> el registro de qué se probó y por qué no alcanzó. **No reimplementarlo por el camino
> de detectar el fade por energía de frame.**
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

**v2.4 publicada (agosto 2026)** — release en GitHub con distribuibles Windows y Linux. Versión de
app 2.4.0, manuales `MANUAL_RadioNoiseKiller_v2.4.pdf` (ES, 44 págs) y `..._v2.4_EN.pdf` (EN, 43
págs). Título "v2.4 by LU6APA". **Salto de menor**: no cambia el significado de ningún control ni el
DSP del cancelador. Es una versión de **afinado y de hacer visible lo que ya pasaba**, y con eso
cierra el hilo del salto del fondo que llevaba abierto desde la v2.2.
- **El umbral de trama del supresor pasa de 5–100 a 2–30, paso 0,25.** Es el cambio con efecto
  audible de la versión: su zona útil contra las ráfagas del fading (3–6) **quedaba por debajo del
  mínimo viejo**, o sea inalcanzable desde la UI.
- **Un indicador de actividad por etapa** del supresor, cada uno arriba de su slider.
- **Los tres sliders que tocan λ_d quedan grises en Perfil estático**, donde no hacen nada.
- **Presets de fábrica de 7 a 5** (se van los dos `Voz natural`), los 5 reafinados en el aire.
- Tres correcciones de documentación que estaban mintiendo: el Refuerzo en agudos listado como
  "solo Adaptativo" cuando funciona en los dos modos, la tabla de anchos rota en el PDF, y el bullet
  de "lo que la app NO hace" que decía no corregir el fading y apuntaba a un módulo que sí lo hace.
- Y un bug de fondo: **el guard de `apply_config` que conserva el nombre del ancho de pasabanda era
  inerte** — habría dado "(modificado)" espurio permanente en los dos anchos que comparten Hz.
- Todo lo audible está validado en el aire. Los bloques "Post-v2.3" de abajo son el detalle.

**v2.3 publicada (agosto 2026)** — release en GitHub con distribuibles Windows y Linux. Versión de
app 2.3.0, manuales `MANUAL_RadioNoiseKiller_v2.3.pdf` (ES, 44 págs) y `..._v2.3_EN.pdf` (EN, 42
págs). Título "v2.3 by LU6APA". **Salto de menor**: no cambia el significado numérico de ningún
control que sobreviva, pero **saca dos controles y agrega tres**, así que la UI se mueve:
- **Se va el Squelch de voz** y en su lugar entra el **Gate de ruido**, que decide por nivel de
  entrada en dBFS. No hay conversión automática: los dos umbrales miden cosas distintas, y los
  presets viejos cargan con el gate desactivado.
- **Se va el combo Modo (AM/SSB)** y el que ocupa su lugar elige el **ancho de pasabanda** entre 8
  de fábrica. Los presets viejos migran solos y conservan sus Hz exactos.
- **Entran dos sliders del estimador adaptativo**: *Freno de bajada* y *Congelar piso con voz*, los
  dos nacidos del problema del salto del fondo — que no se resolvió con un mecanismo único sino
  combinando controles por condición.
- Todo el contenido salió de escuchar en la radio, con la excepción notable del gate: ése se diseñó
  entero midiendo sobre grabaciones y la escucha lo confirmó sin correcciones.
- Los bloques de abajo que dicen "Post-v2.2" son el detalle de esta versión.

**v2.0 publicada (agosto 2026)** — release en GitHub con distribuibles Windows y Linux. Versión de
app 2.0.0, manuales `MANUAL_RadioNoiseKiller_v2.0.pdf` (ES, 37 págs) y `..._v2.0_EN.pdf` (EN, 36
págs). Título "v2.0 by LU6APA". **Salto de mayor, no de menor**: cambió el corazón del cancelador y,
sobre todo, **el significado numérico de varios controles** (Post-Filtro, Intensidad, Mezcla del
excitador). Los presets de 1.9.x cargan sin error pero no suenan igual — los 8 de fábrica se
reajustaron en el aire. Todo el contenido de abajo se validó escuchando en la radio, con varias
iteraciones de ida y vuelta (ver los "reportado en el aire" de cada ítem: casi todos los fixes de
esta versión salieron de una escucha que contradijo una medición sintética).

**Post-v2.2: el Squelch de voz se reemplaza por un Gate de ruido por nivel** (`src/dsp/gate.py`).
Pedido del usuario, con el diagnóstico ya hecho: *"la verdad es muy poco o casi nulo su utilización.
Muy difícil de calibrar para que esté correcto y sólo uso en SSB"*. El squelch decidía con
`voice_prob_sq` y tenía dos defectos de fondo: (1) **su umbral era un % de una probabilidad que no
aparece en ninguna pantalla**, así que sólo se ajustaba por prueba y error; (2) el VAD se calcula
sobre `snr_post`, que depende de λ_d — medido sobre las grabaciones reales del usuario marcaba
**0,93 en subidas de ruido contra 0,59 en onsets de voz**, o sea invertido.
- **Decide con el nivel de ENTRADA y actúa sobre la SALIDA.** Silenciar la entrada parece lo
  natural, pero deja al estimador midiendo el silencio que el propio gate fabrica: medido sobre una
  grabación real, un gate en la entrada hunde λ_d **9,5 dB**; el mismo gate sobre la salida lo deja
  idéntico. Y cerraría justo en las pausas, los únicos ratos en que MCRA puede medir el ruido. Por
  eso `process(audio, level_db)` recibe por separado con qué decide y sobre qué actúa.
- **El umbral terminó siendo ABSOLUTO en dBFS, y el primer diseño (relativo al piso medido) FALLÓ.**
  La idea era que se auto-calibrara al cambiar de banda —el patrón "un umbral absoluto no es
  portable" del techo de ruido del AGC— pero **el fallo es estructural**: la referencia tiene que ser
  el ruido, y cualquier seguidor de piso o persigue a la señal (y el gate cierra sobre la voz) o no
  sigue al ruido. Medido con las grabaciones de voz continua del usuario, con umbral relativo de
  +6 dB el gate quedaba **cerrado el 100 % del tiempo** atenuando todo 20 dB; agregarle al gate un
  piso propio de subida frenada no lo arregló, porque **el nivel de banda completa se mueve apenas
  ~5 dB entre voz y no-voz** en HF. **Regla: un umbral relativo necesita una referencia que el propio
  control no perturbe; si la referencia sólo puede medirse cuando el control está abierto, no hay
  diseño relativo posible.** El absoluto además es **observable** —se calibra mirando el indicador de
  nivel—, que era justo el reclamo original.
- Lo portable se maneja como el techo del AGC: es **un ajuste por estación**, viaja en el preset y
  viene **desactivado** de fábrica. Rango −80..−20 dBFS, default −50 (verificado bajo los niveles
  medidos del usuario: p5 −37,9 / mediana −34,7 / p95 −33,0 dBFS, así que no puede mutear de
  sorpresa).
- **Atenúa, no mutea**: `gate_depth_db` 0–60, default 20. En HF 15–25 dB suena bastante más natural
  que el silencio digital. Del squelch se conservan la retención, el **cierre progresivo** (mitad
  plena + desvanecimiento, la "cola de squelch" de la v1.3) y la rampa por frame.
- **Módulo de PRIMER NIVEL, no sub-módulo del cancelador** (invariante 2 al revés): el nivel de
  entrada se mide siempre, así que el gate funciona con el cancelador apagado. El squelch vivía
  indentado porque usaba su VAD.
- Se fueron `squelch_*` de DSPConfig, `voice_prob_sq`-como-gate del pipeline, el grupo de Avanzada
  Cancelador, los 2 tooltips y sus claves i18n. **Los 7 presets de fábrica cargan con
  `matches()==True`** con las claves muertas del squelch adentro y sin las del gate — cuarta vez que
  paga la normalización por `snapshot()` (invariante 10), y **no se regeneraron a propósito**.
- El gate corre **después del limitador** y se saltea en Preview (es una etapa que se dispara con la
  señal, como las cuatro que ya se salteaban). Diagrama del pipeline regenerado.
- **VALIDADO EN EL AIRE** (agosto 2026: *"funciona como lo esperado"*). El diseño se decidió entero
  sobre grabaciones y banco —incluido el vuelco de relativo a absoluto— y la escucha lo confirmó sin
  correcciones, que en este proyecto es la excepción: casi todos los fixes de la v2.2 salieron de una
  escucha que **contradijo** una medición. Lo que hizo la diferencia acá fue medir sobre el material
  real del usuario desde el principio, no sobre señales sintéticas.

**Post-v2.3 — el supresor de impulsos en valores agresivos SÍ ayuda con los subidones del fading, y
un limitador dedicado NO lo mejora (medido, agosto 2026). VALIDADO EN EL AIRE** con el control ya
re-escalado: *"dimos en la tecla, es notorio la reducción del efecto que estábamos persiguiendo"*.
**Cierra el hilo del salto del fondo**, que llevaba diez enfoques descartados — y no lo cerró una
búsqueda mía sino que el usuario notó el efecto ajustando presets, con un mecanismo que ya estaba en
el código desde siempre y que nadie había mirado para esto. **Regla de método: cuando una búsqueda
larga se queda sin ideas, preguntarle al operador qué encontró tocando; el que escucha todos los
días prueba combinaciones que ningún banco propone.** Observación del usuario ajustando presets. Se midió sobre 4 de sus grabaciones reales, con la cadena **sincrónica** (blanker → AGC →
pasabanda → MCRA), nunca por el pipeline con su hilo.
- **Existe el efecto, pero no es el que parecía.** El **pico** del subidón no se mueve (+9,7 → +8,9
  dB en el extremo). Lo que baja es la **brusquedad** — el p95 del escalón de nivel entre bloques de
  20 ms — y eso sí es monótono con el umbral.
- **NO es específico del fading, y me corregí a mí mismo.** En la grabación que miré primero la
  especificidad (cuánto más baja adentro de los subidones que afuera) daba −0,88 dB; replicada en
  las 4 da **−0,47 de media con el signo dado vuelta en una**. Es un **suavizador de transitorios
  general**; se luce en el fading porque los subidones son los saltos más bruscos que hay. **Regla:
  una diferencia entre dos zonas de UNA grabación no es una propiedad hasta replicarla.**
- **El prototipo dedicado midió PEOR y se descarta.** Un limitador propio (umbral en dB, ventana de
  0,5 s, ataque/release propios) da especificidad **+0,00 a +0,48** — o sea que actúa MÁS afuera de
  los subidones — contra −0,88 del blanker, y no mejora la brusquedad a igual costo de voz. Se
  probaron releases de 5, 20 y 250 ms: los tres igual. **No reimplementarlo.**
- **El que trabaja es el umbral de TRAMA; el de MINI es contraproducente.** Bajar sólo trama
  (**4/7**) da brusquedad **−0,62 dB** por −0,01 dB de voz; bajar los dos (**4/4**) da **−0,56** —
  *peor* — por −0,18 de voz. La etapa de trama es, funcionalmente, un limitador de transitorios con
  referencia de ~0,5 s (mediana de 25 bloques), y dispara **6× más seguido dentro de los subidones**
  (19,8 % contra 3,2 % de los bloques).
- **RIESGO CONCRETO, y es el hallazgo que hay que conservar:** con el umbral **mini** en 4, la
  distorsión sobre **voz limpia sin un solo impulso** es **−8,7 dB**, y en 2/2 **−6,3 dB** — *peor
  que el diseño roto de antes de la v2.2* (−6,6 dB), el que el usuario reportó como "distorsión
  notoria de la voz". Con mini en 7 y trama en 4 queda en −21,3 dB, comparable al default. **Bajar
  el mini para perseguir este efecto es volver al bug que la v2.2 arregló.**
- **HECHO — el slider de trama se re-escala de 5–100 a 2–30, paso 0,25.** Y el problema era peor
  que "poca resolución", que es lo que el usuario reportó (*"no podía hacer un ajuste fino"*): el
  slider **arrancaba en 5** y la zona útil es **3–6**, o sea que arrancaba POR DEBAJO del mínimo y
  desde la UI no se podía llegar. Por eso el usuario terminaba bajando el umbral MICRO, que es
  justo lo que le opacaba la voz — el síntoma y la causa encajan exactamente.
  - Arriba de ~20 la etapa no dispara, así que el 80 % del recorrido viejo no hacía nada. El nuevo
    máximo de 30 es seguro: **ningún preset de fábrica ni el settings guarda más de 30** (se
    verificó antes de tocarlo; si lo hubiera, cargarlo lo recortaría y marcaría "(modificado)").
  - **El clamp del DSP se deja en 2–100, más ancho que el slider a propósito** — es el lado seguro
    del invariante 1: un preset viejo con un valor alto no se recorta al cargarlo.
  - Etiqueta cualitativa retocada (`muy agresivo` < 4, `agresivo` < 8, `normal` < 18, `suave`), y
    tanto la nota como el tooltip y los dos manuales explican la segunda función y **advierten
    explícitamente que el micro no es el camino**, con la cifra de distorsión al lado.
  - Test `test_ui::test_umbral_de_trama_llega_a_la_zona_util`: el mínimo alcanza la zona útil, el
    paso permite 4,00 y 4,25, y los dos extremos llegan enteros al DSP sin que el clamp los recorte.
  - **VALIDADO EN EL AIRE**: *"dimos en la tecla, es notorio la reducción del efecto que estábamos
    persiguiendo"*.
- **Y el indicador de Actividad era uno solo para las DOS etapas** — lo preguntó el usuario
  (*"¿el medidor de arriba es sólo para ese control? ¿el micro no tiene?"*) y la respuesta era peor
  que "es de los dos": **el número lo domina la etapa mini**, porque suma un disparo por cada
  mini-trama de 0,67 ms mientras la de trama suma uno por bloque. Medido sobre una grabación real:
  con los umbrales por defecto la trama aportaba el **9,8 %** del total; con la trama en 4 sube al
  **44 %**. O sea que el único indicador disponible estaba **arriba del slider que menos reflejaba**,
  y mover ese umbral casi no movía la aguja.
  - `pop_hits()` pasa a devolver `(trama, mini)` y hay **un indicador por etapa, arriba de su
    slider**. Es la misma clase de defecto que tenía el squelch: un control que se ajusta sin poder
    observar lo que hace — y pesa más ahora que a la etapa de trama se le documentó una segunda
    función.
  - **Un solo `pop` por tick, y las dos etapas juntas**: si se leyera una por vez, la primera lectura
    le vaciaría el contador a la otra y una de las dos no se encendería nunca. El test lo fija.
  - Test `test_ui::test_supresor_tiene_un_indicador_por_etapa`: cada indicador cuenta lo suyo (con la
    otra etapa en cero el suyo queda en "—") y las dos se encienden en el mismo tick.
  - **VALIDADO EN EL AIRE.** Con los dos indicadores separados, bajar el umbral de trama se ve subir
    la Actividad de trama sin mover la de micro: la confirmación visual de que se está tocando la
    etapa que corresponde y no la que opaca la voz.

**Post-v2.3: los presets de fábrica pasan de 7 a 5, y los 5 se reafinan con el umbral de trama nuevo**
(agosto 2026 — ver [[project_factory_presets]]). El usuario borró **`Voz natural - AM` y
`Voz natural - SSB`**: *"no tenían sentido de tener y mantener"*. Eran de la v1.7, cuando la receta
"Intensidad baja + post-filtro alto" era un hallazgo nuevo; hoy esa receta está en los otros presets
y en el capítulo de calibración, así que los dos eran una copia que había que mantener al día en cada
cambio de esquema. **La receta se conserva en el manual, sin la referencia a los presets.**
- Los 5 que quedan traen ya el **umbral de trama en su zona útil**: 3 en `AM SW Ruido Alto`, 5 en
  `AM Local`, 7 en `AM SW Ruido Medio`, contra los 15–30 de antes. Los dos de SSB quedan en 10 y 15,
  o sea que ahí el techo a las ráfagas no se busca — coherente con que el fading fuerte es de las
  bandas de AM de onda corta.
- **El gate quedó activado en los 5**, con umbrales de estación distintos. Confirma otra vez que ese
  valor no viaja: el default de fábrica sigue siendo "desactivado" por eso mismo.
- **Barrido de todo lo que afirmaba "7"**, que es donde se cuela el error silencioso: README (dos
  lugares), el comentario de `noise_floor` en `config.py`, el paso de verificación del zip en el
  skill de release, y la receta del manual ES+EN que decía "está lista como presets de fábrica".
- De paso, el preset semilla de `test_ui` se llamaba **igual que uno de fábrica** y se leía como si
  el test dependiera de él, cuando en realidad lo crea el propio test. Renombrado a
  `___preset_de_prueba___`. **Regla: un fixture no debe llamarse como un dato real del usuario.**

**Post-v2.3: tres presets de fábrica más, reafinados en el aire con el gate ya validado** (agosto
2026 — ver [[project_factory_presets]]). Cambian `AM SW - Ruido Alto y Fading`,
`SSB - Ruido ALto -Perfil Adaptativo` y `SSB - Ruido Medio -Perfil Adaptativo`. **Salen en la v2.4.**
- **El gate queda activado en dos de los tres** (`AM SW Ruido Alto` y `SSB Ruido Medio`, los dos con
  umbral **−40 dBFS**, hold 300 ms y profundidad 20 dB), así que ya van tres de siete con el gate
  puesto y todos con un umbral calibrado en la estación del usuario. Confirma que el control se usa
  y que el valor **no es portable**: −30 dBFS en AM Local contra −40 en los otros dos.
- **Los dos SSB pasan a `bandpass_preset: "Personalizado"`**: la migración les conservó los Hz del
  modo SSB que tenían (100–2700), que no coinciden con ningún ancho del catálogo. Es exactamente el
  comportamiento buscado — el combo no miente sobre lo que suena.
- Patrón del resto: **piso perceptual más suave** (`perceptual_floor_boost` 1.0 → 0.5 en dos) y
  **`noise_freeze_thr` bien por encima del default** (0.75 y 0.50 contra 0.30), que es el control
  nuevo haciendo lo que se esperaba con voz continua. `AM SW Ruido Alto` además afloja el cancelador
  (`noise_alpha` 0.75 → 0.6, `noise_floor` 0.15 → 0.10) y acelera el AGC a `fast`.
- **Se colaron en el commit del fix de gating por un `git add -A`** — el mismo descuido que ya
  costó una vez con `errores_dsp.log`, y encima contra el acuerdo explícito de no commitear presets
  del usuario sin su OK. El usuario decidió conservarlos. **Regla operativa: al commitear con
  cambios del usuario en el árbol, listar los archivos a mano.**

**Post-v2.3: tres sliders del cancelador quedaban vivos y sin efecto en Perfil estático.** Pregunta
del usuario (*"¿hay varios controles de avanzadas que no se utilizan en estático?"*) que resultó
correcta. **Sale en la v2.4** — se arregla en `main`, pero no se re-publicaron los assets de la v2.3.
- **Reactividad del piso, Freno de bajada y Congelar piso con voz** tocan **sólo a `λ_d`**, que
  existe únicamente en modo Adaptativo (`_mcra_feed` se llama dentro del `if self._mode == "mcra"`).
  En estático el piso sale del perfil aprendido y es fijo. Medido: con cualquier valor de los tres,
  la salida del profiler en estático es **idéntica bit a bit**.
- **`refresh_enabled_states` sólo miraba `noise_enabled`, nunca el modo**, así que los tres se veían
  habilitados, se movían, mostraban su etiqueta y guardaban el valor en el preset sin producir nada.
  Es el invariante 6 (chequear el modo en TODOS los efectos) aplicado a la UI, que era donde
  faltaba. `_on_noise_mode_changed` ahora re-evalúa el gating; `reload()` ya lo hacía.
- **Y había un error en el sentido contrario, que le escondía un control útil al usuario: el
  Refuerzo en agudos SÍ funciona en estático.** Multiplica el `noise_mag` efectivo venga de donde
  venga (línea fuera de la rama de modo), y medido pesa lo mismo en los dos modos. Los **manuales**
  lo listaban como "(solo Adaptativo)" — el tooltip y la nota del slider estaban bien. Corregido, y
  de paso los manuales explican por qué los otros tres aparecen grises.
- **Método:** la pregunta se contestó **midiendo** —correr el profiler en estático variando cada
  slider y comparar la salida muestra a muestra— y no leyendo el código. Leer alcanzaba para los
  tres muertos, pero es lo que hubiera repetido el error del manual sobre el cuarto: la línea del
  refuerzo está lejos de la rama de modo y "se parece" a un parámetro de MCRA.
- Test `test_ui::test_sliders_de_lambda_d_solo_en_adaptativo`: los tres grises en estático, vivos en
  Adaptativo, **el refuerzo en agudos vivo en los dos** (si no, el fix se pasaría de largo), y que el
  gating sobreviva a apagar y prender el cancelador. `test_noise_fall_slider` sumó la dimensión modo.

**Post-v2.2: los 4 presets de fábrica de AM/SSB reafinados con los controles nuevos** (agosto 2026,
afinados al aire por el usuario — ver [[project_factory_presets]]). Cambian `AM Local - RuidoMedio`,
`AM SW - Ruido Alto y Fading`, `AM SW - Ruido Medio y Fading` y `SSB - Ruido ALto -Perfil Adaptativo`.
- **El patrón, y es el resultado de toda la investigación de esta tanda:**
  - **`noise_hf_boost` a 0.0** en los tres que lo tenían (0.5, 1.0 y 1.5). Es el hallazgo medido:
    costaba 1,0–1,6 dB de voz por ~0 dB de fondo en este receptor.
  - **`noise_fall_db_s` explícito en los cuatro** (10 en AM SW Ruido Alto, 20 en los otros tres):
    confirma que el freno se elige por condición y no hay un valor único.
  - **`noise_freeze_thr` distinto en cada uno** (0.3 a 1.0), ídem.
  - **`agc_noise_ceiling_enabled` vuelve a True en los cuatro** — estaban todos en false desde la
    tanda anterior, cuando el techo causaba subidones; con el freno de apertura de la v2.1 el
    problema ya no está y el usuario lo reactivó.
  - Más presencia (varios pasan a 2000 Hz / +4,5 a +6 dB), que es lo que compensa el brillo que ya no
    aporta el refuerzo en agudos.
- **Se regeneraron pasando por `_capture()`**, así que se fueron solas las claves muertas
  (`noise_fading_*` de la v2.2 y `pitch_shift_hz`). Verificado que los **7** cargan con
  `matches()==True`, o sea sin "(modificado)" espurio (invariante 10).

**Post-v2.2: los indicadores quedaban congelados al DETENER (invariante 5, otra vez).** Reportado
sobre el **AGC de entrada**: al detener el proceso se quedaba con el último valor medido.
- **La causa no es un early-return sino el TIMER**: todo lo que se pinta únicamente en
  `_tick_levels` se congela, porque ese timer se detiene junto con el procesamiento. El `else` del
  propio tick nunca llega a correr. **Variante del invariante 5 que no estaba anotada: no alcanza
  con que el indicador tenga su rama de reposo — si su timer se detiene, esa rama no se ejecuta.**
- **Eran cuatro, no uno.** Además del AGC de entrada: el del **limitador de picos**, el **S/N** y los
  **marcadores de heterodino** de la cascada. Los que sí volvían a reposo (VU, latencia, nivelador,
  techo del AGC) lo hacían por una lista de líneas sueltas dentro del `else` de
  `_on_toggle_processing`, que es justo la forma de que al agregar el quinto nadie se acuerde.
- **Fix:** `_reset_live_indicators()` en un método propio, con TODO lo que sólo pinta `_tick_levels`.
  Un indicador nuevo tiene ahora un lugar evidente donde declarar su reposo.
- De paso, dos casos del mismo invariante en el indicador del AGC: el tick lo actualizaba con `if`
  sin `else` (apagar el AGC dejaba el valor pegado) y `_on_agc_changed` lo limpiaba a `""` en vez de
  a `"—"`, o sea desaparecía en lugar de mostrarse en reposo.
- Test `test_ui::test_indicadores_vuelven_a_reposo_al_detener`: se les mete un valor "vivo" a los
  siete, se detiene, y **ninguno puede seguir mostrándolo**. El test enumera los indicadores por
  nombre, así que al agregar uno hay que sumarlo ahí — que es la idea.

**Post-v2.2: el estilo del botón ACTIVO se unifica en la regla global.** Pedido del usuario: que la
letra del botón que se pone rojo quede **amarilla y en negrita**.
- **La causa de la disparidad estaba a la vista una vez mirada:** la hoja global ya ponía
  `QPushButton:checked { background-color: #c62828; ... }`, o sea **fondo rojo a cualquier botón
  activado**, y encima cada botón traía su propio estilo inline. El **Mute quedaba con letra ROJA
  (#ef5350) sobre el fondo rojo** del :checked — ilegible —, el Bypass en amarillo (lo puse hoy) y
  Grabar y ACTIVAR con el gris por defecto. Tres criterios distintos para el mismo estado.
- **El color va en la regla global, no inline en cada botón.** Un estilo inline **PISA** la hoja
  global, así que mientras existieran los inline no había forma de unificar desde un solo lugar.
  Ahora `QPushButton:checked` lleva también `color: #ffd600; font-weight: bold;` y los cuatro
  botones quedaron **sin estilo propio** — incluido ACTIVAR/DETENER, que también es checkable y
  arrastraba el problema sin que nadie lo hubiera notado.
- Lo propio de cada botón pasa a ser sólo el **texto** (`Grabar/Detener`, `Bypass/Crudo`,
  `Mute/Silenciado`). Cualquier botón checkable que se agregue hereda el aspecto correcto solo.
- Test `test_ui::test_boton_activo_letra_amarilla_y_negrita`: la regla global tiene el amarillo y la
  negrita, **y ningún botón de la fila la sobreescribe**. El segundo assert es el que importa — sin
  él, un inline nuevo rompería la unificación sin que nada fallara.
- Hubo que corregir dos asserts viejos que comprobaban `btn.styleSheet()` no vacío como prueba del
  estado activo: comprobaban justo lo que se sacó a propósito. Ahora comprueban el cambio de texto.

**Post-v2.2: Grabar / Bypass / Mute con ancho uniforme (`_ACTION_BTN_W = 140`).** El usuario pidió
120 porque los de 150 se veían vacíos. **Medido con `QFontMetrics`, 120 no alcanza**: `"⏺  Grabar"`
pide 122 px y `"⏹  Detener"` 134.
- **El hallazgo real del barrido: los TRES ya recortaban su estado ACTIVO.** `"⏹  Detener
  grabación"` pedía **254 px** en un botón de 150, `"⇄  Sin procesar"` 194, y `"🔇  Silenciado"` 170
  en uno de 120. El ancho fijo de cada uno se había elegido mirando **sólo el texto en reposo**.
  **Regla: el ancho de un botón que cambia de texto se calcula con el texto MÁS LARGO de todos sus
  estados, no con el inicial.**
- Textos activos acortados para que entren: `"⏹  Detener grabación"` → **`"⏹  Detener"`** y
  `"⇄  Sin procesar"` → **`"⇄  Crudo"`** (consistente con "señal cruda", que es el vocabulario de
  los manuales). En EN: `"⏹  Stop"` y `"⇄  Raw"`.
- **140 y no 134** (el mínimo justo) porque **el ancho de los emoji depende de la fuente del
  sistema**: sin holgura, en otra máquina el texto sale con "...". Es el mismo tipo de cuidado que
  el resto de los anchos fijos de la UI.
- **`"🔇  Silenciado"` (170 px) sigue recortándose** y se dejó a propósito: es una palabra que eligió
  el usuario, y en 140 recorta MENOS que antes en 120. Queda como decisión suya cambiarla
  (`"🔇  Mudo"` entra en 98) o ensanchar los tres.
- Test `test_ui::test_botones_de_escucha_mismo_ancho_y_sin_recortes`: mismo ancho los tres, y
  ningún texto de ningún estado se elide — **en los dos idiomas**, porque las traducciones cambian
  el largo (`"Detener"` mide 134 y `"Stop"` 98).

**Post-v2.2: el Bypass pasa de casilla a botón, junto a Grabar y Mute.** Pedido de UX del usuario.
Los tres son **acciones de escucha** que se aprietan y se sueltan mientras se opera, no ajustes que
se dejan puestos — tenerlos juntos y con la misma forma es más coherente que dejar uno como casilla
en el grupo Control. Queda a la izquierda del Mute, que sigue anclado al borde derecho.
- **No se deshabilita con el proceso detenido**, a diferencia de Grabar y Mute: dejarlo preparado
  antes de activar es útil, y como la ganancia de salida se recuerda por modo
  (`_out_gain_by_bypass`), se puede calibrar cada lado sin audio. Es una diferencia deliberada, no
  un olvido — el test la fija.
- Estado visual como el Mute pero en **ámbar** (`#ffd600`), no rojo: bypass es un estado normal de
  comparación, no un corte. `_refresh_bypass_button` centraliza el texto y el estilo.
- `_check_bypass` → `_btn_bypass`. El rename no era obligatorio (un `QPushButton` checkable tiene
  el mismo `setChecked/isChecked`), pero dejar un atributo llamado `_check_*` para un botón es una
  mentira que después cuesta.
- Manuales ES+EN: la fila del grupo Control se convierte en una sección propia junto a la de Mute,
  con el aviso de que **en bypass el estimador adaptativo no puede calibrar** — que enlaza con el
  bug de arriba.
- Test en `test_ui::test_bypass_es_boton_junto_al_mute` (es botón, está en la fila del Mute, no
  requiere proceso, llega al pipeline, cambia texto y estilo, y **no quedó ninguna casilla vieja**).

**Post-v2.2 — RESUELTO: "el estimador adaptativo no completa la calibración" era el BYPASS.**
Cierra las cuatro ramas de diagnóstico fallidas que este archivo venía acumulando. El usuario lo
reportó como *"pasó cuando seleccioné SSB muy angosto, y falla siempre"* — el preset era una
coincidencia, estaba comparando con Bypass puesto.
- **En bypass `_process` devuelve antes de encolar** al hilo procesador, así que el cancelador no
  corre y el estimador no recibe **ni un frame**. Pero `db_in` se mide una línea ANTES del
  `if self._bypass` (línea 1279 contra 1281), así que el diagnóstico mostraba audio normal.
  Resultado: `frames=0 quar=0 ld=None db_in=-28.6 errores=0` — **la firma exacta de un fallo real**,
  y por eso mandó a buscar el problema al lado equivocado durante cuatro rondas.
- **Reproducido y confirmado**: con bypass ON el pipeline da exactamente esa firma; con bypass OFF,
  127 frames y λ_d presente. Los 8 anchos del catálogo arrancan bien, headless y por la UI.
- **Fix (tres partes):** (1) `_update_noise_db` detecta el bypass ANTES de contar ticks y muestra un
  cartel **gris explicativo**, no el aviso rojo de falla; (2) **no acumula `_mcra_wait`** en bypass,
  para que al salir empiece de cero y no aparezca ya en rojo; (3) `mcra_diag` reporta `bypass=` como
  **primer campo** — era justo el dato que faltaba en el log.
- **Lección de método, y es la que importa:** el diagnóstico enumeraba tres causas conocidas
  (excepción del DSP, cancelador desactivado, falta de audio) y **le faltaba el estado que hace
  imposible calibrar por diseño**. Un detector de "esto no funciona" tiene que empezar por los
  estados en los que **no debe funcionar**; si no, reporta como falla algo correcto, y con una firma
  indistinguible de la falla real. El log lo hubiera dicho en la primera ronda con un campo más.
- **Cómo se encontró, después de cuatro rondas de hipótesis:** no reproduciendo (headless y por la
  UI daba bien con los 8 anchos) sino **leyendo el orden de las líneas** de `_process` a partir de la
  única pista dura del log — `quar=0`, que dice que la cuarentena no recibió nada, no que el
  estimador esté atascado. **Cuando el repro no falla, el dato que sobra en el log es el que
  discrimina.**
- Test permanente en `test_ui::test_mcra_en_bypass_no_es_falla` (cartel sin ⚠, no rojo, ticks en 0 y
  `bypass=True` en el volcado). El `_Pipe` falso de `test_mcra_stall_reason` declara `bypass = False`
  explícitamente, para que ese test siga probando el caso de falla de verdad.

**Post-v2.2: `errores_dsp.log` estaba versionado.** Se coló en un `git add -A` mío. Es diagnóstico de
la máquina del usuario y ya causó una vez que se tomara por fallo real lo que había dejado la propia
suite de tests. Sacado del índice y agregado a `.gitignore` con el motivo escrito al lado.

**Post-v2.2: se elimina el modo AM/SSB; el combo pasa a ser "Pasabanda". VALIDADO EN EL AIRE**
(agosto 2026: *"el refactor del pasabanda quedó ok, podemos cerrar eso"* — revisión funcional y de
sonido con los 8 anchos). Pedido del usuario:
*"con la llegada de los Presets no tiene sentido mantener el combo Modo"*. Tenía razón — el modo
sólo elegía qué tupla de límites usaba el pasabanda, así que con presets que ya traen la banda,
elegir modo y después ancho era decir dos veces lo mismo. **Lo que el operador elige es el ANCHO.**
- **`RadioMode` desaparece del proyecto.** Se verificó antes de tocar nada que **nada más dependía
  del modo**: ningún módulo DSP ramifica por AM/SSB, sólo `BandpassFilter` lo usaba para indexar su
  dict de límites. Por eso el cambio, que parecía grande, es acotado.
- `bandpass_limits` y `bandpass_out_limits` pasan de **dict-por-modo a un solo par `(lo, hi)`**.
  Campo nuevo `bandpass_preset: str` con el nombre del ancho elegido (o `"Personalizado"`).
  Catálogo `BANDPASS_PRESETS` en `config.py` — 8 anchos (4 SSB, 4 AM) elegidos por el usuario.
- **UI:** el combo de Principal pasa de *Modo* a *Pasabanda*; Avanzada Audio queda con **un solo
  par** de sliders de entrada y uno de salida, en vez de cuatro pares. El filtro de salida **no**
  lleva combo, a propósito: es un retoque fino sobre el ancho ya elegido, casi siempre definido en
  relación a la entrada (más ancha), y un segundo combo con la misma lista sumaba control sin
  agregar decisión.
- **Migración sin cambio de sonido, y verificada sobre los datos reales.** `_leer_limites()` acepta
  los dos formatos: con el viejo (dict + campo `mode`) toma el par **del modo que estaba activo**.
  Verificado sobre los 7 presets de fábrica y el `settings.json` del usuario: **todos conservan sus
  límites exactos y ninguno marca "(modificado)"** (invariante 10). El par del otro modo se
  descarta, que es justo lo que ahora cubre el preset.
- **Dos trampas del rediseño, ambas resueltas y con test:**
  1. **`set_bandpass_limits` re-deriva el nombre a partir de los Hz**, para que mover un slider
     ponga el combo en "Personalizado" solo (si no, el combo mentiría sobre lo que suena). Pero eso
     pisaba la elección del usuario cuando **dos entradas comparten los mismos Hz** (*SSB ancho* y
     *AM 3 kHz*): elegir la segunda saltaba a la primera. `set_bandpass_preset` fija el nombre
     **después** de aplicar los límites, y `apply_config` hace lo mismo. Test:
     `test_bandpass_preset_ambiguo_no_salta`.
  2. **`_refresh_bandpass_combo` bloquea señales**: sin eso, sincronizar el combo desde el config
     dispara su propio handler y vuelve a aplicar el preset (bucle).
  3. **El mismo guard en `apply_config` era INERTE, y lo destapó el release.** Estaba escrito como
     "aplico los setters y después restauro `self._config.dsp.bandpass_preset = dsp.bandpass_preset`",
     que en la UI **no hace nada**: `config` y `self._config` son el MISMO objeto, así que
     `set_bandpass_limits` ya había pisado el nombre y la línea se asignaba el valor corrupto a sí
     misma. Hay que **capturar el nombre ANTES** de tocar los setters. **Regla: un guard que
     "restaura" un valor no sirve si la fuente y el destino pueden ser el mismo objeto — sólo se ve
     al probarlo por el camino en que lo son.** Síntoma: `"(modificado)"` espurio permanente en
     cualquier preset guardado con uno de los dos anchos que comparten Hz.
     - **Cómo apareció:** el test de "(modificado)" empezó a fallar recién al correr la suite
       ENTERA, porque depende de qué ancho dejó puesto el test anterior. Suelto pasaba siempre.
       Vale como recordatorio de que **el orden de los tests es parte del test**.
     - El guard nuevo comprueba las dos direcciones: que el nombre ambiguo sobreviva a
       `apply_config`, y que un nombre que **no** corresponde a los Hz vigentes sí se re-derive (si
       no, el combo mentiría sobre lo que suena). Verificado que falla con el código viejo.
- **Regresión que casi se me pasa: hay OTRO combo llamado "Modo:"** — el de Perfil estático /
  Adaptativo, dentro del grupo del cancelador. Al limpiar el catálogo i18n de las claves del modo
  AM/SSB **borré también su clave** y se quedaba sin traducir. Restaurada, y los manuales ahora
  aclaran cuál es cuál. **Regla: antes de borrar una clave de i18n por “el control ya no existe”,
  buscar el texto en el código — dos controles distintos pueden compartir etiqueta.**
- Manuales ES+EN: el control se documenta con la tabla de los 8 anchos, la aclaración de que combo y
  sliders son el mismo ajuste visto de dos maneras, y el aviso de que los anchos grandes no sirven
  si el receptor no entrega señal ahí arriba (se verifica con la curva de Entrada del espectro, que
  enlaza con la nota de por qué el piso amarillo parece cortarse).

**Post-v2.2: el squelch de portadora trababa el estimador — CUARTA vez que muerde la trampa
autorreferencial.** Encontrado midiendo por qué el cancelador se lleva tanta voz. La detección de
"se cortó la portadora" comparaba la energía del frame contra **λ_d**, o sea contra la salida del
propio estimador que después alimenta.
- **Estado absorbente:** con señal fuerte y pausas reales, λ_d queda alto → las pausas caen 13 dB por
  debajo → se leen como portadora cortada → se saltean **justo los únicos frames en los que el
  estimador puede medir el ruido** → λ_d nunca baja.
- **Medido con ruido CONOCIDO** (voz con pausas de 1 s cada 3 s, S/N +15 dB): disparaba en el
  **16,9 %** de los frames y dejaba λ_d **+16,2 dB** por encima del ruido real. Con la referencia
  arreglada: **0 %** y **−0,1 dB**. A S/N +6 dB no disparaba ni antes ni después — **el bug crece con
  la calidad de la señal**, que es lo que lo hacía invisible: aparece justo cuando todo lo demás
  anda bien.
- **Fix:** la referencia pasa a ser un seguidor de mínimos de la **ENTRADA** (`_sq_ref_min`, ventana
  de 4 s en subtramas, el mismo patrón que MCRA y que el techo del AGC). Un hueco entre palabras se
  queda EN el piso del canal (sigue entrando portadora y ruido) y no dispara; una portadora cortada
  se va muy por debajo y sí. Verificado que el feature sigue sirviendo: con la portadora cortada
  −40 dB dispara el 6,5 % de los frames. Exención de arranque obligatoria (`None` hasta que la
  ventana se llena una vez), si no cualquier frame flojo del principio parece portadora cortada.
- **NO es lo que el usuario está escuchando**: sobre sus 8 grabaciones de onda corta dispara el
  0–1,1 % y λ_d no cambia. Se arregla igual porque el escenario donde sí muerde —señal fuerte con
  pausas— es **AM local**, donde el usuario también opera.
- **Regla, ahora con cuatro casos:** ningún detector que decida CONGELAR un estimador puede tomar su
  decisión a partir de la salida de ese estimador. Van: el freeze de MCRA por vp (v2.0), el
  congelamiento del AGC por VAD (v2.1), el detector de estimado obsoleto (post-v2.2) y éste.
- **Trampa propia en el guard, corregida antes de commitear:** el primer test replicaba la condición
  del squelch **afuera** del profiler, así que medía mi copia de la fórmula y daba verde con el
  código viejo. Detectarlo por "S_f no cambió" tampoco servía: el freeze por voz y la cuarentena
  dejan S_f quieto porque ni llaman al update. El detector exacto es **`_mcra_frames` avanzó Y S_f no
  cambió**, porque el contador se incrementa antes de la rama del squelch. Con eso el guard da 0 %
  con el código nuevo y **96,4 %** con el viejo.

**Post-v2.2 — el cancelador se lleva 6–8 dB de la banda de voz. El post-filtro queda CERRADO; el margen está en la etapa base.** Salió de
medir por qué el usuario escucha distorsión. En sus 8 grabaciones el S/N de la voz sobre el piso es
**+13,5 a +25,8 dB** (señales cómodas, no enterradas): un Wiener ideal a ese S/N tocaría la voz
**0,2 dB**, y la cadena le saca **6,6 a 8,3 dB**.
- **Causa identificada y resuelta: `noise_hf_boost` al 100 %.** Cuesta **1,0–1,6 dB de voz** (3,6 dB
  en 2,5–3,5 kHz, la banda de las consonantes) y compra **0,2 dB de fondo** — nada. Consistente en
  las 5 grabaciones medidas. El motivo enlaza con la nota del manual sobre la curva amarilla: **la
  radio del usuario no entrega nada arriba de ~4 kHz**, así que la rampa del refuerzo (que crece
  desde 2,5 kHz) cae donde hay voz y ya no hay ruido, inflando λ_d 2–3 dB sobre las consonantes.
  **VALIDADO de oído por el usuario.** Regla: el refuerzo en agudos sólo sirve si el receptor
  entrega ruido por encima de donde arranca la rampa; se verifica mirando hasta dónde llega la curva
  de **Entrada** en el espectro.
- **Lo que queda: el post-filtro se lleva 3,8 dB de voz, y es intrínseco a su diseño.** Aplica
  profundidad por `(1 − p_speech)`, y con `p_speech = min(g_detect/0.80, 1)` un bin necesita **+6 dB
  de S/N propio** para quedar protegido. Medido en frames dominados por voz: la **mediana de
  `p_speech` en la banda de voz es 0,35**, el 98 % de los bins queda bajo 0,9 y el **87 % de la
  ENERGÍA de la voz** vive en bins que el post-filtro puede tocar. A fuerza 4 son 18 dB de
  profundidad, así que un bin con p=0,5 recibe 9 dB de recorte.
- **Dos intentos de arreglo, los dos DESCARTADOS por medición:**
  1. **Profundidad del post-filtro escalada por el S/N del frame.** No se activaba: mi rampa asumía
     que `snr_db` reportaba el S/N real, y **lee 2–3,4 dB** cuando el S/N de la voz es +13 a +26
     (es media de banda completa sobre media de λ_d, otra magnitud). Falla con la firma "la perilla
     no mueve nada" (k medio 0,92–0,96).
  2. **Bajar `_VAD_THRESHOLD`** (los +6 dB por bin): de 0,80 a 0,35 gana 1,0 dB de voz pero pierde
     1,3 dB de fondo y el balance **empeora** (−2,4 → −2,1). Es "suprimir menos" con otro nombre.
- **Trampa de medición propia, importante:** comparar λ_d contra "el mínimo real de su propia
  ventana" **está viciado** — el mínimo de N muestras baja solo al crecer N, así que el sesgo
  aparente cambia con el hop y con la ventana sin significar nada (daba +10,5 a hop 960 y +17,8 a
  hop 240). Lo mismo con el percentil 10. **Para medir el sesgo de un estimador de ruido hace falta
  ruido conocido**, y con eso el resultado fue otro: el sesgo depende del S/N, no del suavizado
  (`_MCRA_ALPHA_S` no cambió nada: 17,3 dB en todo el barrido) ni de la ventana.
- **CERRADO por medición: el trade del post-filtro es UNIDIMENSIONAL.** Se probaron cinco caminos y
  los cinco caen sobre la misma curva que mover el slider. La comparación correcta es **a igual daño
  de voz**, interpolando la curva del propio slider (post 0→8: voz −6,5→−10,1 dB, fondo −8,3→−14,4):

  | enfoque | resultado |
  |---|---|
  | Profundidad escalada por el S/N del frame | La perilla no se activaba (`snr_db` lee 2–3 dB) |
  | Refuerzo de pitch más fuerte | 0,5 dB de vocales en todo el rango, y cuesta 1,5 dB de fondo |
  | Bajar `_VAD_THRESHOLD` (0,80 → 0,35) | +0,4 dB de media, **entre −0,2 y +1,1** según grabación |
  | Protección de consonantes por contexto | **PEOR** que el slider a igual voz (−0,5 a −0,8 dB) |
  | ORÁCULO con etiquetas perfectas | No hay techo: la separación **empeora** (−14,5 → −13,0) |

- **Qué se rompe con la protección por contexto, y explica el oráculo:** el post-filtro tiene un
  freno de retirada (`_POST_RELEASE_DB`, 12 dB/frame). Si se lo suelta durante la voz, cuando llega
  el hueco todavía viene bajando y llega tarde — se pierde más supresión en el hueco de lo que se
  gana en la consonante.
- **Se corrige un descarte anterior mal fundado:** el umbral VAD se había desestimado como "suprimir
  menos con otro nombre". El motivo correcto es que **cae sobre la misma línea** y gana apenas
  0,4 dB con signo inconsistente. La comparación original no normalizaba por daño de voz — **regla:
  al evaluar una alternativa a un control existente, compararla contra ese control en el punto que
  iguala el costo, no en su valor por defecto.**
- **Diagnóstico útil que sale de camino: el post-filtro NO era el principal culpable.** Con post 0 el
  daño a la voz ya es **−6,5 dB**; a post 5 (el del usuario) es −9,1. O sea que el **cancelador base
  se lleva 6,5 dB y el post-filtro agrega 2,6**. El margen grande está en la etapa base — Intensidad,
  piso espectral y sobre todo **la exactitud de λ_d**. Ése es el próximo hilo, y hay que abrirlo
  midiendo el sesgo de λ_d **con ruido conocido**: todas las referencias derivadas del propio audio
  (percentil por bin, mínimo por ventana) están estadísticamente sesgadas y dan números que cambian
  con el hop y la ventana sin significar nada.
- **Qué SÍ se comió el post-filtro, medido:** consonantes **−11,5 dB** contra vocales −6,5 (las
  fricativas son anchas y aperiódicas, así que a `p_speech` le parecen ruido), y dentro de las
  vocales, bins de entremedio −8,3 contra picos armónicos −3,7. El desglose fue lo que hizo pensar
  que había margen; la medición mostró que no lo hay **a nivel de frame**.

**Post-v2.2: el umbral del freeze de MCRA pasa a ser ajustable ("Congelar piso con voz").** Slider
30–100 % en Avanzada Cancelador (`noise_freeze_thr`, default 0.30 = comportamiento previo; 1.00 =
no congela nunca). **VALIDADO EN EL AIRE**: se expuso justamente porque la medición daba empate, y
la escucha resolvió lo que la medición no podía — los presets de fábrica terminaron con un umbral
DISTINTO en cada uno (0,3 a 1,0), que es la confirmación de que el valor correcto depende de la
condición y de que el control tenía que existir.
- **El material del usuario es voz CONTINUA**, dato que él aportó y que invalidó varias mediciones
  mías (ver el bloque de abajo). Con voz continua el freeze bloquea **entre el 67 % y el 98 % de los
  frames** según la grabación (medido sobre 7), y λ_d se queda sin material para seguir las subidas
  de ruido. Ese es el mecanismo por el que el piso llega tarde.
- **ORÁCULO — la medición que cierra la discusión sobre "mejorar la detección de voz".** El usuario
  propuso mejorar el VAD (autocorrelación mejorada, o **Silero VAD** neuronal). Se midió con un
  detector PERFECTO sobre un banco con verdad conocida (voz continua + salto real de ruido de
  +10 dB):

  | freeze | frames que alimentan λ_d | sigue el salto de +10 dB |
  |---|---|---|
  | actual (autocorrelación) | 50–75 % | +7,2 / +8,1 dB |
  | **ORÁCULO (perfecto)** | **2 %** | **+0,0 dB** |
  | ninguno | 100 % | +8,4 / +9,8 dB |

  **Un detector perfecto es estrictamente el PEOR de los tres.** Con voz continua congela siempre y
  λ_d no aprende nunca; el detector actual funciona *porque se equivoca*. **Regla: cuando el
  problema es que un estimador se queda sin datos, mejorar el detector que le corta los datos
  empeora las cosas.** No reproponer Silero ni ninguna mejora del VAD para este síntoma. (Sí
  tendría sentido para el **squelch**, el **nivelador** y el **gate del excitador**, que dependen
  del `voice_prob` de energía; y ahí habría que pesar el costo: `onnxruntime` son 15–50 MB en unos
  distribuibles que se vienen achicando, rompe el "todo numpy/scipy puro" del proyecto, y el A6 de
  2 núcleos es la referencia de CPU.)
- **La opción "detección por armonicidad" ya estaba implementada**: es exactamente este gate
  (`_pitch_autocorr` + `_MCRA_PITCH_THR`). Y la premisa de que *"el ruido atmosférico es totalmente
  aleatorio"* **no se cumple** en HF real: medido sobre el material del usuario, el ruido de banda da
  mediana 0,212 pero **p90 0,518**, contra voz real de mediana 0,544 y p10 0,201 — se solapan de
  lleno. Portadoras, heterodinos, estaciones adyacentes y el propio pasabanda correlacionan el ruido.
- **Por qué slider y no constante:** las mediciones dan **empate**. Sobre las 7 grabaciones, freeze
  activo vs desactivado da la MISMA deriva media de λ_d (+0,2 dB) y la MISMA rugosidad del fondo
  (8,8 dB); el fondo mejora 4–6 dB en dos grabaciones y empeora un poco en tres. Lo único robusto es
  que sin freeze λ_d es más **predecible** (dispersión de la deriva 2,0 dB contra 5,5).
- **El guard sintético NO puede decidir esto y hay que saberlo:** `voice_sig` es más sostenida y
  periódica que la voz real (mediana de periodicidad 0,80 contra 0,544), así que la contaminación de
  7,4 dB que justificó el freeze en la v2.0 puede ser un artefacto del banco. Es la trampa ya
  documentada ("una señal demasiado limpia da un falso MAL resultado") vista otra vez.
- Guards nuevos en `test_noise_vad`: clamp == rango del slider, que el default siga congelando
  (2 % alimenta), que en 1.00 **no congele nunca** (100 % alimenta — sin el chequeo explícito
  `_freeze_thr < 1.0` un umbral de 1.00 seguiría disparando en frames perfectamente periódicos), y
  que en 1.00 la voz sostenida **sí** contamine (+9,7 dB): el control tiene que mover lo que dice
  mover, y ése es el riesgo que expone a propósito. Test de UI: el slider muestra 30–100 % y el DSP
  trabaja en 0.30–1.00, que es justo donde un factor 100 se pierde sin que nada falle.

**Post-v2.2 — CORRECCIÓN de método: el material es voz CONTINUA, y eso invalidó mediciones propias.**
El usuario lo aclaró después de que yo insistiera dos veces con que sus grabaciones no tenían voz.
Vale registrar el error completo porque el patrón es caro:
- **Mi criterio de "hay voz" era ≥10 dB sobre el piso, y está mal para este dominio.** Con voz a S/N
  cercano a 0 dB —que es EL caso de uso de la app— la voz nunca cruza ese umbral. Cinco detectores
  míos fallaron en confirmarla: nivel (0 %), modulación silábica (2,47× contra 5,41× de referencia),
  peine armónico (0,283 vs 0,318, no discrimina), el VAD de la app (46 % vs 52 %, inútil — es la
  trampa de realimentación) y el rango dinámico (6,2 vs 8,4 dB).
- **Qué se cayó con la corrección:** (1) la afirmación *"el freeze dispara sobre el ruido, es un
  falso positivo"* — con voz continua el freeze estaba haciendo lo correcto; (2) toda la comparación
  de planitud espectral "ruido vs voz", que en realidad comparaba voz fuerte contra voz floja; (3) el
  encuadre entero de buscar un **árbitro** que distinga "subió el ruido" de "arrancó la voz" — con
  voz continua no hay arranques que confundir, el problema es sólo que MCRA se queda sin comer.
- **Y me apuré con una muestra chica**: reporté +3,5 dB de deriva de λ_d con el freeze activo sobre
  **2** grabaciones; sobre las **7**, la media es idéntica con y sin freeze. Es exactamente el error
  contra el que este archivo advierte en tres lugares.
- **Regla: antes de medir sobre material del usuario, confirmar con él QUÉ hay en la grabación.**
  Preguntar sale gratis y cinco detectores automáticos no lo resolvieron.

**Post-v2.2 — DESCARTADO por medición: planitud espectral (SFM) como árbitro.** Propuesta del
usuario contra el salto del fondo: la voz tiene picos armónicos (planitud baja) y el QRN es de banda
ancha (planitud alta), así que SF + RMS distinguirían el brote de ruido del arranque de voz.
- **Es el primer árbitro de los tres con el SIGNO correcto** (d' positivo), a diferencia del VAD y de
  la periodicidad, que estaban invertidos. El razonamiento era bueno: SFM se calcula sobre el
  espectro crudo, así que no puede realimentarse con λ_d.
- **Dos correcciones a los rangos citados**, medidas: (1) **el techo de la SFM no es 0,95 sino
  ~0,56** — con una FFT finita cada bin de ruido es exponencial y la media geométrica sobre la
  aritmética converge a `exp(−γ)=0,5615`; ruido blanco puro mide 0,562. (2) A S/N bajo **la voz se
  aplana sola**: voz+ruido a 0 dB da 0,26, y el fondo de una grabación real da 0,17 — o sea que ahí
  la voz sucia es MÁS plana que el ruido y el árbitro se da vuelta.
- **Sin punto de operación usable:** a umbral 0,40 atrapa 36 % de las subidas pero dispara sobre
  **6,6 %** de los frames de voz; a 0,50 la voz está a salvo pero atrapa 0 %.
- La variante que parecía mejor —medir si la subida es **pareja en todos los bins** en vez de la
  planitud del frame— **se quedó sin muestras** (3 eventos contra 6). No se pudo evaluar; no cuenta
  ni a favor ni en contra.
- Ojo: parte de estas cifras se calcularon con el etiquetado voz/ruido que después resultó inválido
  (ver la corrección de arriba). Lo que **sí** sobrevive es el techo de 0,56 y el aplanamiento de la
  voz a S/N bajo, que son propiedades medidas y no dependen del etiquetado.

**Post-v2.2: freno de CAÍDA de λ_d — la primera cosa que mueve el salto del fondo.** Idea del
usuario, después de diez enfoques descartados: *"el piso de ruido cae muy abruptamente y luego de
esto viene la subida sin poder reaccionar. ¿Se puede pensar en que el piso no tenga cambios tan
abruptos hacia abajo (pero siga rápido hacia arriba)?"*. `_MCRA_FALL_DB_S = 10.0` dB/s: λ_d no puede
bajar más rápido que eso, subir queda libre.
- **La premisa literal es FALSA y conviene dejarlo escrito:** λ_d sube y baja al mismo ritmo (p90 de
  0,25 dB por frame en ambos sentidos, ratio 1,01). No cae más abrupto de lo que sube. **El freno
  funciona igual**, por otro motivo: el salto ES la supresión que se pierde mientras λ_d va atrasado,
  así que si el estimado no se hunde en los ratos flojos, la distancia a recuperar en la subida es
  menor. Una idea puede ser correcta con el mecanismo equivocado — medir igual.
- **Medido sobre las 5 grabaciones reales** (exceso del piso de salida 1,5 s después de una subida):
  libre **+2,5 dB** | 20 dB/s +1,7 | **10 dB/s +0,6** | 5 dB/s −0,3 | 2 dB/s −0,3. Y de yapa la
  supresión SUBE (19,7 → 20,8 dB) y el escalón de ganancia de banda ancha BAJA (0,70 → 0,62 dB).
- **EL CONTROL DECISIVO, y es el que separa esto de los diez callejones: NO es "suprimir más".** A
  igual supresión (~20,8 dB), el freno deja el exceso en **+0,6 dB** con escalón 0,62; llegar a esa
  misma supresión bajando el piso espectral a 0,09 da **+2,7 dB** y 0,79. Ídem con Intensidad 0,85
  (+2,5 / 0,77) y post-filtro 5,5 (+3,4 / 1,05). **Todas las perillas que ya existían empeoran el
  síntoma al suprimir más; ésta lo mejora.** Sin este control no se podía distinguir el mecanismo
  nuevo de la palanca vieja, que era la conclusión de todo el bloque ABIERTO.
- **Precio**, en dos partes: **~0,5 dB de voz** (p90 de la salida, −5,9 → −6,4) y tardar más en
  aprovechar una banda que se limpia de verdad (bajada real de 10 dB: **0,7 → 2,1 s**). En ese rato
  lo único que pasa es que suprime de más — el lado que el usuario reportó como inofensivo.
- **El pico inicial casi no se mueve** (+6,9 → +7,0 a 10 dB/s; recién a 2 dB/s baja a +4,8). Lo que
  el freno arregla es la **persistencia**, no el golpe. Honestidad sobre qué se resolvió.
- **Efecto colateral que hubo que reparar: el indicador de S/N.** λ_d deja de ser un estimado neutro
  del piso y pasa a ser uno conservador, así que el indicador leía **1,8 dB menos** y `test_integration`
  dejaba de discriminar voz de ruido. Se lleva **una recursión paralela sin frenar**
  (`_mcra_ld_medido`), pasada por la misma curva de refuerzo en agudos. **Primer intento fallido,
  anotado:** guardar "el λ_d de este frame antes de frenarlo" NO sirve — se calcula a partir del λ_d
  frenado del frame anterior, así que arrastra todo el sesgo acumulado y el indicador no se movía ni
  un dB. Hace falta la recursión propia. No es exacta (α_d lo sigue calculando el camino frenado):
  el apartamiento queda bajo 1 dB contra los −1,8 de antes.
**VALIDADO EN EL AIRE, con el default cambiado a SIN FRENO (30 dB/s).** El usuario probó los dos
valores y reportó: *"con ruido más bajo y mayor S/N el freno funciona; en AM Local puedo usarlo en
10 dB/s sin problemas"*, y sobre una grabación de onda corta con QRN alto, que 30 (sin freno) era
mejor que 10.
- **Su oído detectó algo que mi métrica titular escondía.** Yo medía "supresión" como piso de entrada
  menos piso de salida, pero **con voz continua ese piso INCLUYE voz**, así que contaba como mejora
  lo que en parte era voz comida. Desglosado por banda en frames dominados por voz, el freno de 10
  saca **1,5 a 3 dB más de voz en TODAS las bandas**, y pega más fuerte justo en 800–1500 Hz y
  2500–3500 Hz, las dos zonas de la inteligibilidad.
- **El control rehecho con la métrica corregida SÍ sostiene que el freno es un mecanismo propio:** a
  igual voz perdida, da cola +2,3 dB contra +4,2 y pico +6,2 contra +10,5 de bajar el piso espectral.
  O sea que funciona; lo que pasa es que cobra en voz, y en banda mala la voz no tiene con qué pagar.
- **El costo depende casi por completo del S/N**, medido con una subida real de ruido de +8 dB:

  | S/N | voz que cuesta el freno de 10 dB/s | ganancia en seguimiento |
  |---|---|---|
  | +18 dB | 0,02 dB | +0,00 dB |
  | +12 dB | 0,03 dB | +0,00 dB |
  | +6 dB | 0,22 dB | +0,52 dB |
  | 0 dB | **1,19 dB** | +1,10 dB |
  | −6 dB | **2,54 dB** | +0,10 dB |

  Despreciable arriba de +6 dB, y se dispara abajo de 0. Exactamente lo que describió el usuario.
- **Default 10 → 30 (sin freno).** El modo de falla a S/N bajo es daño a la voz, que es justo lo peor
  y lo más difícil de diagnosticar; y S/N bajo es cuando uno recurre al cancelador. Mismo criterio
  que el techo de ruido del AGC: cuando el valor correcto depende de la estación o la banda, el
  default es "desactivado". Manual ES+EN con la tabla de costo por S/N y la regla operativa (AM local
  10 dB/s, onda corta con QRN 30), apuntando al indicador de S/N de la pestaña Espectro para saber en
  qué régimen se está.
- **Al mover el default hubo que sacar cuatro guards de `_MCRA_FALL_DB_S`**: usaban la constante como
  "el valor con freno", y con el default en 30 (= `_FALL_OFF`) habrían comparado dos corridas
  idénticas y pasado sin probar nada. Ahora usan `_FALL_TEST = 10.0` explícito. **Es la tercera vez
  en esta tanda que un guard queda mudo por depender de un default que cambia** (pasó con
  `_MCRA_FALL_DB_S` al volverse slider y con `_MCRA_PITCH_THR`): **un guard nunca debe tomar del
  default el valor que está probando.**
- **Hallazgo grande que queda abierto, medido de paso:** en el material de onda corta del usuario, con
  el freno APAGADO, el cancelador saca **14–17 dB de la banda de voz** en los frames donde la voz
  domina, y el **93 % de los bins de voz sale atenuado más de 6 dB**. El balance entre lo que se le
  quita al fondo y lo que se le quita a la voz es de apenas **3,2 dB**. Es mucho más margen que el que
  quedaba en el salto del fondo, y probablemente sea la distorsión que el usuario viene reportando
  desde el principio. **Próximo hilo a tirar.**

- **Expuesto como slider "Freno de bajada" (2–30 dB/s, default 30 = sin freno)** en Avanzada Cancelador, a
  pedido del usuario para comparar valores de oído. Califica según la regla de la v2.1 porque los dos
  extremos son defendibles — más lento = mejor síntoma pero más costo de voz y más lentitud ante una
  banda que se limpia —, a diferencia del freno del techo del AGC, donde una punta era siempre peor.
  **30 dB/s es en la práctica "sin freno"**: la caída natural de λ_d medida sobre las grabaciones
  llega como mucho a ~23 dB/s, así que el tope del slider sirve de A/B contra el comportamiento
  previo. `noise_fall_db_s` en DSPConfig, persistido en settings.json y presets; clamp del setter ==
  rango del slider (invariante 1). **Pendiente decidir si queda como control o vuelve a constante.**
- **Al pasar de constante a slider, el estado vivo dejó de ser `_MCRA_FALL_DB_S`** (que ahora es sólo
  el default) y pasó a `_fall_db_s`. Los guards que pisaban la constante de clase **después** de
  construir el profiler dejaron de tener efecto y comparaban dos corridas idénticas — se veía porque
  el check "el freno de verdad está actuando" empezó a reportar el mismo número en las dos ramas.
  Hay que moverlo con `set_fall_db_s()`.
- Guards nuevos en `test_noise_vad`: que λ_d no caiga más rápido que el freno, **que el freno de
  verdad esté actuando** (sin él cae 14,8 dB/s contra 9,0), que no limite la subida, que valga lo
  mismo en dB/s a cualquier hop (es property, invariante 9) y que no arrastre el indicador de S/N.
  **Dos trampas propias en esos guards:** (1) probar la caída con −25 dB daba verde sin ejercitar
  nada, porque por debajo de `_MCRA_SQUELCH_RATIO` se activa la detección de "se fue la portadora" y
  congela todo el estado MCRA — hay que usar −8 dB; (2) medir la subida como *delta en dB* daba un
  falso fallo, porque con freno λ_d **parte de más arriba** (que es el mecanismo) y termina igual o
  más alto: hay que comparar el NIVEL al que llega, no cuánto subió.
- **VALIDADO EN EL AIRE** — ver el bloque de arriba: el usuario comparó los dos extremos escuchando,
  y de ahí salió el default en 30 (sin freno). Los presets de fábrica traen `noise_fall_db_s`
  explícito y distinto en cada uno, o sea que el slider se quedó como control.

**Post-v2.2: la máscara del refuerzo de pitch no discriminaba, y su efecto dependía del bloque.**
Detectado por el usuario de oído: *"el refuerzo de pitch de voz exagera mucho el problema también, al
deshabilitarlo mejora"*. Tenía razón, y la causa es un defecto de años.
- **`_PITCH_SIGMA` valía 1.5 BINS.** La máscara tiene que cumplir dos cosas que viven en dominios
  distintos: cubrir el pico del armónico (~2 bins de lóbulo de ventana — cantidad en **bins**) y no
  llegar hasta el armónico vecino (que está a f0 — cantidad en **Hz**). Un sigma fijo en bins sólo
  cumple la segunda por casualidad del f0 típico, porque la separación entre armónicos *medida en
  bins* escala con el tamaño de FFT.
- **Medido, la media de la máscara en la banda útil:** 0,82–0,99 a hop 480 contra 0,20–0,46 a hop
  1920. O sea que con bloques chicos la máscara valía ~1 en TODO el espectro: el refuerzo dejaba de
  proteger armónicos y se volvía **un piso global de `p_speech` de 0,7**. Con eso ningún bin baja del
  0,3 con el que el post-filtro decide qué es ruido → **el post-filtro se apaga entero y el indicador
  "Reducción extra" cae a 0**, que era el otro síntoma que el usuario reportó y yo no supe explicar.
- **Es el mismo defecto que mató la criba armónica en la v2.2** (*"con bloque 480 la máscara vale
  1,00 de media"*), pero ahí se descartó el feature y acá seguía vivo en uno activo — y en los **7
  presets de fábrica**, todos con el refuerzo encendido.
- **Costo medido sobre las grabaciones reales** (bloque 960): con el refuerzo activo, **2,9 dB menos
  de supresión** y el **doble de escalón de ganancia de banda ancha** (0,70 → 1,35 dB entre frames
  consecutivos). Eso último es la firma del crujido, la misma métrica que destapó el post-filtro.
- **Fix:** `sigma = max(_PITCH_SIGMA_MIN=1.0 bin, _PITCH_SIGMA_K=0.12 · separación_en_bins)`. Codifica
  las dos restricciones. Resultado: escalón 1,35 → 1,08 dB, supresión 16,8 → 17,6 dB, indicador en 0
  del 3,3 % al 2,1 % (= el valor con el refuerzo apagado).
- **Se evaluó σ fijo en Hz y se descartó pese a medir un pelo mejor** (0,94 dB de escalón y 17,9 de
  supresión con σ=15 Hz). Es la formulación físicamente equivocada —satisface el ancho del pico sólo
  por accidente— y la diferencia (0,14 dB sobre 5 grabaciones) está dentro del ruido de la medición.
  La proporcional además es **la más consistente entre bloques y voces** (dispersión de la media de
  la máscara 0,126 contra 0,201 del σ en Hz y 0,284 del original). **Regla: entre dos fórmulas que
  miden casi igual, elegir la que expresa la restricción real, no la que gana por un decimal.**
- **Límite que NO se puede arreglar y quedó documentado:** con bloque 480 y una voz de 150 Hz, los
  armónicos están a 3 bins y **no existe ningún bin entre armónicos** (el banco lo delató devolviendo
  NaN al promediar "entre armónicos"). Ninguna σ discrimina ahí. Manuales ES+EN y tooltip ahora dicen
  que este módulo pide **bloque 960 o 1920**.
- **La selectividad real del feature es chica en todos los casos** (+0,7 a +1,2 dB de protección
  diferencial entre armónicos y lo de al lado). Con 2–3 dB de supresión de costo, dejarlo apagado es
  una decisión razonable — que es a la que había llegado el usuario solo.
- **No había NINGÚN test de DSP del refuerzo de pitch.** Cuatro guards nuevos en `test_noise_vad`:
  que la máscara cubra el pico (≥0,85), que no puentee entre armónicos separados ≥6 bins (≤0,30),
  que no imponga un piso global de `p_speech` y que **no dependa del tamaño de bloque**. Verificado
  que los dos últimos **fallan con la fórmula vieja** — un guard que no puede fallar no prueba nada.
- **Los 7 presets de fábrica traen el refuerzo activado**, así que todos cambian de sonido: suprimen
  algo más y modulan menos. **Re-escuchados y reajustados en el aire** (agosto 2026), en dos tandas:
  la de los 4 de AM/SSB y la de `AM Local` + `AM SW Ruido Alto` que cierra la v2.3.

**Post-v2.2 — el fondo salta cuando el ruido de banda sube. DIEZ enfoques descartados, y una resolución PRÁCTICA (agosto 2026).**
Reportado con un diagnóstico del usuario que resultó correcto en la cadena causal: *"cuando baja el
ruido no se perciben problemas, a lo sumo se cancela un poco de más. Cuando sube el ruido, el piso no
llega a subir a tiempo y la salida sube muy de golpe"*.
- **Medido sobre 5 grabaciones reales** (22 eventos de cambio de piso ≥5 dB). La asimetría es real:
  ante una SUBIDA de ruido de +5,1 dB el piso de salida se va a **+8,4 dB** (exceso **+3,4 dB**) y
  tarda >1,5 s en acomodarse; ante una BAJADA de −5,6 dB la salida cae **−9,5 dB** (exceso −3,9), o
  sea suprime de más. El retardo del estimador es simétrico; **lo asimétrico es la molestia**.
- **Dato clave para no perder tiempo: lo que salta es el FONDO, no la voz.** Durante esos eventos la
  parte alta de la salida se mueve **+1,2 dB** mientras el fondo se mueve +8,4 dB, y el fondo está
  **15,3 dB por debajo** de la voz. Cualquier procesado que actúe por NIVEL (compresor, limitador,
  ducker) no puede separarlos: el umbral que alcanza al fondo aplasta la voz.
- **NO HAY ÁRBITRO para distinguir "subió el ruido" de "arrancó la voz"** en el instante del evento,
  y esto está medido dos veces:
  - **El VAD está INVERTIDO**: vp 0,93 en subidas de ruido contra 0,59 en onsets de voz reales
    (vp_sq 0,71 vs 0,34). Es la trampa de realimentación ya documentada dos veces en este archivo —
    vp se calcula sobre `snr_post`, que depende de λ_d; si λ_d va atrasado, TODO parece señal.
  - **La periodicidad tampoco**: d' = **−0,74** (0,28 en subidas de ruido vs 0,22 en onsets). En el
    primer frame de una palabra la autocorrelación todavía no tiene material periódico en su ventana.
- **Los siete enfoques probados y por qué murieron** (no reintentar sin leer esto):

  | Enfoque | Resultado medido |
  |---|---|
  | Freno de CAÍDA de ganancia por bin | Sin efecto: el escalón del arranque es hacia ARRIBA |
  | `beta_fast` (Velocidad de ataque) | Sin efecto en todo el rango (pozo −9,4 dB constante) |
  | Ventana de ataque de `p_speech` | −9,4 → −9,0 dB |
  | Bloque más grande (960/1920) | **Peor**: rugosidad 6,3 → 12,6 dB |
  | Reactividad del piso más corta | **Peor**: exceso +0,9 → +3,8 dB y menos supresión |
  | Detector de estimado obsoleto + resync | Falsos positivos; y el resync no acelera (rearma sobre voz) |
  | Ruido de confort | Métrica OK (fluctuación 7,4 → 5,1 dB) pero **rechazado de oído** |
  | Compresor de salida | El fondo está 15 dB bajo la voz: ningún umbral los separa |
  | Freno de subida del piso de salida | Duckea 4,1 dB permanentes por 1,7 dB de mejora |
  | Look-ahead del estimado (0–800 ms) | **No hay futuro que mirar**: λ_d no sube NADA en 1,5 s |
  | Freeze de MCRA partido (seguidor vivo, λ_d congelado) | Sin efecto: +2,3 vs +2,5 dB |
  | Freeze de MCRA por bin (sólo los armónicos) | 43 % de bins actualizando, pero −2,3 dB de supresión |

- **Dato duro que acota el problema, medido al probar el look-ahead: el estimador se alimenta en el
  12,5 % de los frames.** El freeze de MCRA por voz se arma con un solo frame periódico y retiene
  200 ms, así que en un QSO tapa hasta los huecos entre palabras, que son justo los frames que MCRA
  necesita. Por eso λ_d no se mueve durante el evento. **No se puede sacar**: verificado contra el
  guard que lo justificó en la v2.0, sin freeze la voz sostenida sube λ_d **7,4 dB**. Los dos intentos
  de aflojarlo sin romperlo están en la tabla de arriba.
- **La única palanca que funciona es cuánto se suprime.** El salto ES la supresión que se pierde
  durante el retardo: si el cancelador quita 20 dB y por un segundo no los quita, el salto es de
  20 dB. Piso más alto o Intensidad más baja → salto proporcionalmente menor. Es el mismo trade que
  aparece en todo este archivo.
- **Trampas de medición propias en este recorrido** (patrones a reconocer): (1) tres bancos
  sintéticos fallaron con la firma *"todas las variantes dan lo mismo"* o *"la dispersión se come la
  diferencia"* — lo que destrabó todo fue medir sobre las **grabaciones reales del usuario**;
  (2) un prototipo del freno de piso medía el nivel sobre la señal YA corregida y se realimentaba
  hasta atenuar 107 dB; (3) se tomó por evidencia un `errores_dsp.log` que había dejado la propia
  suite de tests (ver el fix de higiene abajo).
- **RESUELTO EN LA PRÁCTICA, no con un arreglo único.** Conclusión del usuario tras probar todo al
  aire: *"con estos nuevos controles y cambios se puede controlar mucho mejor el fading y además
  perder menos voz; por ahora es la mejor solución que encontramos a este difícil problema"*. No
  apareció EL mecanismo que borra el salto; lo que funciona es **combinar tres cosas, ajustadas por
  condición y guardadas en el preset**:
  1. **Freno de bajada** (nuevo) — el único mecanismo propio que se encontró: a igual voz perdida
     mejora la cola y el pico más que cualquier perilla vieja. Se elige por S/N (10 dB/s con señal
     cómoda, sin freno con señal débil; la tabla de costo está en su bloque).
  2. **Congelar piso con voz** (nuevo) — afloja el freeze cuando el estimador se queda sin frames.
  3. **Refuerzo en agudos en 0** — 1,0–1,6 dB de voz recuperados por ~0 dB de fondo en este equipo.
  Más los dos bugs de fondo que se arreglaron por debajo (máscara armónica del pitch dependiente del
  bloque, y el squelch de portadora comparándose contra λ_d).
- **Lo que NO hay que volver a proponer está en la tabla de arriba.** Y la conclusión de método que
  deja el recorrido: en este problema **no hay un arreglo único que lo cierre**; el avance vino de
  controles por condición que el operador elige escuchando. Antes de buscar otra vez "la solución",
  releer la tabla y el bloque del daño a la voz.

**Post-v2.2: `test_pipeline` escribía en la carpeta de datos REAL.** El test inyecta a propósito una
curva de piso corrupta (`np.ones(7)`) para verificar la recuperación del hilo DSP, y `run_all.py`
aísla con `RNK_DATA_DIR` — pero corriendo el archivo suelto no había variable y el `errores_dsp.log`
resultante caía en la carpeta del proyecto. **Costó tiempo real**: ese log se tomó por un fallo en la
máquina del usuario y se llegó a anunciar como "la causa raíz que faltaba desde la v2.1", cuando era
el propio test. Ahora `test_pipeline` se crea su temp dir si corre solo, con el mismo guard que ya
tenía `test_ui` (invariante 11). **Regla: un test que escribe en la carpeta de datos deja evidencia
indistinguible de un fallo real.**

**Post-v2.2: el post-filtro retiraba su profundidad de golpe y eso crujía.** Reportado en el aire:
*"cuando una voz pasa de un nivel bajo a una pronunciación más fuerte produce una distorsión"*, y
por separado un ruido cíclico que hacía subir el volumen. **Diagnosticado sobre una grabación real
del usuario** (entrada + procesado sincronizados) después de que tres bancos sintéticos fallaran.
- **Mecanismo:** el post-filtro resta una profundidad fija ponderada por `(1 − p_speech)` — a fuerza
  6 son ~27 dB. Durante la pausa hunde el fondo; cuando arranca la palabra `p_speech` salta a 1 y
  esos 27 dB **desaparecen en un solo frame**. Medido sobre el audio real: escalón de ganancia de
  **+9,8 dB en 10 ms** en el 10 % peor de los arranques. Eso es lo que se oye.
- Interacción de diseño: la v2.0 hizo a propósito que `p_speech` **no se suavice** en los arranques
  (para que la voz no sonara "limitada"). Ese fix hace que `p_speech` salte, y el post-filtro
  convierte ese salto en un escalón de 27 dB. Dos features correctas que juntas hacen daño.
- **Fix:** el factor del post-filtro puede **hundirse al instante** pero sólo **retirarse
  `_POST_RELEASE_DB = 12` dB por frame**. Escalón **+9,8 → +2,1 dB**, supresión en huecos **mejora**
  0,7 dB, ataque de la palabra cuesta 1,6 dB.
- **El valor salió de un barrido y el óptimo no es el que más baja el escalón:** frenando más el
  escalón sigue cayendo (a 3 dB/frame da −2,1) pero el arranque de la palabra sale **12 dB más
  atenuado** — exactamente la "voz limitada" de la v2.0. La tabla completa está en el comentario de
  la constante. **No bajarlo sin mirar la columna del ataque.**
- **Bajar el slider NO era la solución**, aunque el escalón dependa de él: el usuario comparó los
  renders y prefirió post 6 y 3 sobre post 0 — *"el resto se escucha más ruido de fondo"*. Por eso
  el arreglo tenía que conservar la profundidad de régimen.
- **Cuatro hipótesis mías descartadas por medición antes de dar con ésta** (valen para no
  repetirlas): (1) el nivelador acumulando ganancia — medido, con voz floja el VAD da vp=0,18 y el
  nivelador queda **congelado justo cuando la voz es floja**; (2) frenar la CAÍDA de la ganancia —
  sin efecto, porque el escalón es hacia ARRIBA y yo limitaba hacia abajo; (3) `beta_fast` y la
  ventana de ataque de `p_speech` — sin efecto; (4) el excitador — sin efecto (con y sin, idéntico).
  Y el bloque más grande **empeora** (rugosidad 6,3 → 12,6 dB).
- **Método:** los tres bancos sintéticos fallaron con la misma firma — *"todas las variantes dan lo
  mismo"* o *"la dispersión se come la diferencia"*. Lo que destrabó el diagnóstico fue medir sobre
  la **grabación real del usuario**, que es para lo que existe el grabador con canal crudo. Con un
  síntoma que sólo aparece en el aire, grabar sale más barato que inventar la señal.
**Post-v2.2 — EN CURSO: MCRA tarda ~15 s en recuperarse de un cambio grande de sintonía.**
Reportado: *"si desintonizo la radio y la vuelvo a sintonizar, el piso de ruido nunca vuelve a la
misma forma que la primera vez"*. **Reproducido y medido** sobre una grabación real con la secuencia
completa (sintonizado → desintonizado → sintonizado en una sola toma).
- **Primero medí mal:** comparé λ_d en instantes sueltos y concluí que no volvía nunca. λ_d fluctúa
  frame a frame y caí en snapshots desafortunados. Promediando ventanas de 5 s y con control (dos
  mitades del mismo tramo sintonizado: 1,30 dB de diferencia de forma), el cuadro real es:
  desintonizado 7,50 dB de forma y +12,1 de nivel; **+12 a +17 s después de volver, 1,19 dB y
  +1,1 dB — o sea recuperado.** Vuelve, pero tarda.
- **El contraste que explica el reporte del usuario:** al **detener y activar** el estimador se
  arma en <1 s porque el warmup está **exento del freeze por voz**. Al desintonizar y volver no hay
  warmup, y con voz presente el freeze bloquea el **~80 % de los frames** (medido: sólo alimentan el
  19 %). Las dos pruebas no son comparables, y esa es la observación correcta que había detrás.
- **Consecuencia real:** durante esos 12-17 s λ_d queda hasta **+8 dB demasiado alto** → el
  cancelador resta de más → suena a distorsión. Encaja con el otro síntoma reportado.
- **Detector de estimado obsoleto — MEDIDO, pendiente de implementar.** Señal: la mediana móvil (2 s)
  de `potencia_del_frame / λ_d`. En régimen sano el piso queda bien por debajo de la potencia total;
  con el estimado viejo y alto ese margen se cierra. Medido sobre la grabación real: **d' = 2,18**, y
  con umbral **+1 dB detecta el 54 % del período obsoleto con 0 % de falsos positivos** en 10 s de
  operación normal. No hace falta detectar todos los frames: con destrabar la mitad del tiempo alcanza
  para re-converger.
- **DISEÑO: re-entrar en warmup, NO levantar el freeze.** Es el punto que hace viable la idea. Si el
  detector se equivoca y levanta el freeze, **entra voz a λ_d** — el bug que el freeze existe para
  evitar, que costó varias sesiones diagnosticar. Si en cambio resetea el estado MCRA para que
  reconstruya como en un arranque limpio, el modo de falla es ~0,4 s sin supresión: molesto pero
  inocuo. **Regla: cuando un detector nuevo puede equivocarse, elegir la acción cuyo fallo sea
  benigno, aunque detecte lo mismo.** Además reusa un camino ya probado en vez de inventar uno.
- **Bloqueado a propósito por falta de evidencia:** el 0 % de falsos positivos está medido sobre
  **10 s de UNA grabación con UN tipo de perturbación**. Antes de implementar hacen falta 2-3
  grabaciones de escucha normal (sin desintonizar, incluyendo música y señales fuertes) para
  confirmar que no dispara en falso. El usuario está juntando ese material.
- Otros dos chequeos, negativos: el tope del AGC recupera al instante (con y sin el freno nuevo, o
  sea **no es culpa del cambio del techo**), y la curva amarilla del espectro se refresca cada 500 ms
  en Adaptativo (no es un problema de display).

**Post-v2.2: Frecuencia de presencia hasta 3 kHz.** Pedido del usuario: *"en AM tiene sentido ir
más cerca de los 2,5 kHz"*. Slider 1000–2000 → **1000–3000 Hz**.
- **El invariante 1 NO aplicaba acá y conviene saber por qué:** el clamp de `PresenceFilter.set_freq`
  ya era 100–8000 Hz, o sea MÁS ancho que el slider. Ese es el lado seguro del invariante (igual que
  `voice_leveler_max_db`, cuyo clamp interno del AGC es 0–60 contra 0–20 del slider): el problema es
  un clamp más ANGOSTO que el slider, que recorta en silencio. Verificado midiendo la respuesta del
  filtro: pedido 3000 Hz → pico real 3000 Hz, +6,0 dB.
- La etiqueta del slider sumó un tramo: arriba de 2200 Hz muestra **brillo** (antes se quedaba en
  "presencia" hasta el final del recorrido). Clave i18n nueva.
- **Sólo tiene sentido en AM**, y eso se documentó en el tooltip y en los dos manuales: el pasabanda
  de AM llega a 4–5 kHz, pero en SSB la banda termina cerca de 2,7–3 kHz y el filtro de salida se
  come el realce. Sin esa nota, alguien en SSB subiría el control a 3 kHz y no escucharía nada.

**Post-v2.2: el techo de ruido del AGC causaba subidones al volver de un QSB.** Reportado en el
aire, con el diagnóstico ya hecho por el usuario: *"sigue molestando las subidas repentinas... el
culpable es el Techo de ruido, reacciona demasiado lento y deja una ganancia mayor"*. **Correcto**, y
la medición lo confirmó exactamente.
- **Mecanismo:** el seguidor del piso es un **mínimo deslizante de 4 s**. Durante el fade baja al
  instante (el mínimo sigue hacia abajo enseguida), pero para volver a subir tiene que esperar a que
  las subtramas viejas salgan de la ventana. Mientras tanto el tope (`techo − piso`) queda abierto de
  más, el AGC amplifica, y al volver la señal esa ganancia acumulada se descarga de golpe. Medido a
  1 s de recuperada la señal, el piso medido **seguía 20 dB por debajo del real**.
- **Dato que explica la percepción:** el pico absoluto es **el mismo** con el techo activado o
  desactivado (−16,8 dB en ambos). Lo que cambia es que el techo mantiene el nivel normal 4 dB más
  abajo, así que el mismo pico se siente como un salto mucho mayor. Por eso al desactivarlo mejoraba.
- **Fix: el tope se cierra al instante pero se abre frenado** a `_IN_NOISE_OPEN_DB_S = 0.5` dB/s.
  Sobrepico **+8,9 → +4,0 dB**, que es **mejor que desactivar el techo** (+4,9), conservando su
  beneficio (el nivel normal no se mueve). La ganancia del AGC dentro del fade pasa de +12,8 a
  +1,8 dB: ya no hay nada acumulado que descargar.
- **Exención de arranque (imprescindible):** el freno NO aplica hasta que el seguidor llenó su
  ventana una vez (`_in_subs_done >= _IN_NOISE_NSUB`). Al arrancar, el seguidor parte del nivel
  instantáneo —con voz, muy alto— y el tope tiene que poder saltar a su valor real. Sin la exención,
  medido, tardaba **25 s** en converger.
- **Se evaluó exponerlo como slider y se descartó, con criterio explícito.** El eje no tiene dos
  extremos defendibles: más lento es siempre mejor para el síntoma (0,5 → +4,0; 1,0 → +5,8; 2,0 →
  +8,1) y lo único que se paga es tardar en aprovechar una banda más limpia — ante una bajada REAL y
  permanente del piso de 12 dB, el tope se abre en 11 s en vez de 0,8, y en el ínterin sólo amplifica
  un poco menos, sin nada audible. **Regla: un control donde una punta es siempre peor no es una
  decisión del operador, es una constante mal puesta.** Si algún día hay que moverlo según la banda o
  la hora, ahí sí merece slider.
- **VALIDADO en el aire:** *"lo activé y probé, ha mejorado, ya no hay subidones repentinos"*. El
  usuario volvió a activar el Techo, que tenía apagado justamente por este problema.
- **Lo que quedó después NO era el techo: el cancelador EXPANDE el fade.** Medido con un QSB de
  20,3 dB de entrada: la salida **sin** cancelador oscila 17,5 dB (el AGC hasta comprime un poco);
  **con** cancelador, 28,9 dB. Son ~11 dB que agrega el propio Wiener — al bajar la señal cae el
  S/N, cae la ganancia, y la salida cae más que la entrada. Ni el techo ni el nivelador tenían que
  ver (verificado: el freno del techo aporta 0,4 dB de esos 11).
- **La perilla contra eso es el Piso espectral, y hacia ARRIBA.** El piso limita cuánto puede caer
  la ganancia, o sea cuánto puede expandir. Medido en la cadena completa: 0,10 → 0,20 lleva el
  vaivén de 28,9 a 24,7 dB sin tocar la brusquedad; sumarle Intensidad 0,55 llega a 22,7 (contra
  20,3 de la entrada, o sea que deja de expandir). Subir el nivelador también baja el swing pero
  **triplica los saltos** (2,2 → 5,7 dB/300 ms) — no es el camino.
- **Se corrigió una nota que decía exactamente lo contrario.** El tooltip del Piso espectral y ambos
  manuales afirmaban que *"un piso alto transmite más el swing del fading"*, o sea bajalo. Medido,
  es al revés, y se verificó separando voz y ruido: los DOS bajan al subir el piso (voz 27,2→24,6;
  ruido 33,0→23,9 de piso 0,05 a 0,30). La nota venía de la sesión de música con QSB de la v1.8.2 y
  quedó sin re-verificar. Corregido en tooltip, clave EN y los dos manuales, dejando dicho que hasta
  la v2.2 decía lo contrario. **Vale como patrón: una nota de operación que nunca se midió puede
  sobrevivir versiones enteras mandando al usuario para el lado equivocado.**
- **Default de `noise_floor` 0.10 → 0.15.** El costo de subirlo se paga en banda ESTABLE, donde no
  hay fading que compensar: medido, 0,10→0,15 cuesta 1,7 dB de supresión de ruido y 0,10→0,20 cuesta
  3,1 dB. Se eligió 0,15 y no 0,20 —que era lo que pedía el usuario— porque 3 dB de la función
  titular de la app es mucho para quien no tiene QSB, y porque 0,15 ya es el valor de 3 de los 7
  presets de fábrica. **El default es casi inerte de todos modos**: los 7 presets especifican su
  propio piso, así que sólo afecta a una instalación nueva antes de cargar un preset y al
  "Restaurar por defecto".
- **Discrepancia de magnitud anotada:** el beneficio del piso mide 4,2 dB en la cadena completa y
  1,0 dB en el cancelador solo. La dirección es la misma; la magnitud depende de qué más haya
  después. Al citar una de las dos cifras, decir cuál es.
- Tests en `test_pipeline`: el tope no se abre más rápido que el freno, el freno no limita el cierre
  (probado sobre el freno y no sobre el seguidor — el mínimo de 4 s no sube con unos frames de ruido,
  y eso es correcto), y el arranque no queda frenado (con un assert que verifica que la ventana
  todavía NO está llena, para que el test pruebe lo que dice).

**v2.2 — la compensación de fading detectaba sílabas, no fades. ELIMINADA.** El usuario reportó que
con sensibilidad en 10 dB (el máximo) el indicador FADE estaba encendido casi todo el tiempo, y
preguntó si había que ampliar el rango del control o si medía mal. Medía mal.
- **El detector comparaba la energía del frame contra un EMA de 40 ms** (`_FADING_EMA_ALPHA=0.80`).
  La voz sola, sin una pizca de fading, oscila **16,7 dB pico a pico** entre sílaba y hueco — el
  mismo orden que el fade de 20 dB que buscaba. Medido con voz y CERO fading: dispara **~2 veces
  por segundo** a cualquier umbral entre 1 y 8 dB (1/s en 10), o sea el indicador encendido el
  50-100 % del tiempo. Los 2/s coinciden con el ritmo de las palabras: dispara al arrancar y al
  terminar cada una.
- **Ampliar el rango no servía:** a 10 dB seguía disparando y, sobre todo, **seguía sin
  discriminar** — con QSB real la tasa era igual o MÁS BAJA que sin fading.
- **Y el techo del feature era chico aunque el detector fuera perfecto.** Con un **oráculo** que
  sabía exactamente cuándo había fade (misma técnica que descartó la criba armónica): −2,4 dB de
  altibajo a cambio de −1,0 dB de voz, y **sólo con ruido atmosférico** (que se desvanece junto con
  la señal). Con **ruido local** —que no se desvanece— el oráculo no cambiaba **nada** (+0,0 dB).
  Ese es el resultado que cerró la discusión: el problema no era el detector.
- **Lo que SÍ sirve contra el QSB es la Velocidad de respuesta del nivelador de voz.** Medido con
  un desvanecimiento de 20 dB: bajarla de 1500 a 200 ms lleva el vaivén extra de 12,2 a 6,9 dB pp.
  Un release lento va a destiempo —aplica la ganancia de hace un segundo al nivel de ahora— y
  **expande** el fade en vez de compensarlo. **Validado en el aire.**
- Trade documentado en el manual: el recorrido de ganancia del nivelador es a la vez lo que compensa
  el QSB y lo que produce saltos bruscos (6 dB/200 ms → 8,8 dB pp de altibajo pero 2,5 dB/300 ms de
  salto; 3 dB/200 ms → 10,7 y 0,8). Si molestan los saltos, bajar la **Ganancia máxima**, no frenar
  la velocidad.
- **Dos trampas de medición propias, ambas detectadas por el patrón "todas las variantes dan lo
  mismo" o "la dispersión se come la diferencia":**
  1. El primer oráculo daba resultados **idénticos** en sus cuatro variantes: `process()` recalcula
     `_fading_active` internamente y pisaba lo que el banco seteaba antes de llamar. Había que
     forzar `_mcra_freeze_count` (la variable de la que deriva) y dejar el umbral inalcanzable.
  2. Las primeras conclusiones sobre el nivelador salieron de correr el **pipeline completo**, y
     ahí la misma configuración daba 9,9 y 27,7 dB según la semilla — la dispersión tapaba todo.
     Es la trampa que CLAUDE.md ya documentaba (*"el hilo procesador avanza distinto en cada
     corrida"*). Rehecho con una cadena **síncrona** (profiler + AGC del nivelador, sin hilo), la
     dispersión bajó a 1-3 dB y **el signo del resultado se dio vuelta**. Para medir el efecto de
     algo sobre el audio, no usar el pipeline con su hilo: replicar la cadena en sincrónico.
- Se fueron: `noise_fading_comp/_change_db/_freeze_ms` de DSPConfig y presets, el checkbox de
  Módulos, los dos sliders y el indicador FADE de Avanzada Cancelador, `pop_fading_active`, el
  latch, `_FADING_*`, `_mcra_freeze_count` (quedó muerto) y 8 claves de i18n. Presets viejos con las
  claves muertas cargan sin "(modificado)" — tercera vez que paga la normalización por `snapshot()`.

**Post-v2.2: eliminada la Corrección de tono SSB (FrequencyShifter).** Decisión del usuario, que la
había pedido en su momento: *"no es utilizado"*. Un control que nadie usa igual hay que mantenerlo,
traducirlo y que no se rompa. Se fueron `src/dsp/freq_shift.py`, `DSPConfig.pitch_shift_hz`, el
setter del pipeline, la etapa del `process()`, el slider de Avanzada Audio con su nota y su tooltip,
y 4 claves de i18n (`neutro`, `agudo`, la etiqueta y la nota). El separador que lo dividía del EQ de
voz también, que sin él quedaba colgado.
- **Migración: no hace falta ninguna.** `settings.json` y los presets viejos siguen trayendo
  `pitch_shift_hz` y se ignora sola — `from_dict` usa `.get(clave, default)` y la clave ya no se
  pide. Verificado que los 7 presets de fábrica cargan con `matches()==True`, o sea sin
  "(modificado)" espurio: es la **segunda vez que la normalización por `snapshot()` (v1.8) paga**, y
  la primera para un campo ELIMINADO, que era justo el caso que la motivó. Los presets no se
  regeneraron a propósito: la clave muerta es inofensiva y no vale reescribir archivos afinados en
  el aire por cosmética.
- `grave` NO se pudo borrar del catálogo aunque este slider lo usaba: lo comparten el centro del EQ
  de cuerpo y el del piso perceptual. Sí se fueron `neutro` y `agudo`, que eran exclusivos.
- Aprovechando, se completó el **docstring del pipeline**, que listaba una cadena de 2020 (le
  faltaban squelch, nivelador, excitador y graves) y ahora apunta al diagrama canónico. Mismo
  problema que motivó sacar el ASCII del README: dos fuentes de verdad se desincronizan.
- El control **no estaba documentado en ningún manual** — se descubrió al buscarlo para sacarlo. Así
  que no hubo nada que quitar de los PDFs, sólo el bullet del README.

**Post-v2.2: revisión del MCRA — el hold del freeze y el umbral δ.** Revisión pedida por el usuario
("ver si hay algo que se pueda mejorar"), hecha instrumentando el estimador real con señales
sintéticas. Dos cambios, **ambos VALIDADOS en el aire** (agosto 2026): el usuario confirmó el
comportamiento que predecía la medición — menos fondo entre las palabras cuando el ruido de banda
se mueve durante una transmisión larga, sin pérdida audible de voz.
- **`_MCRA_VOICE_HOLD_MS` 300 → 200 ms.** Con huecos de palabra normales (~400 ms) el hold se comía
  casi todo el hueco y el estimador se quedaba sin frames para ponerse al día durante una
  transmisión larga. Los números y el barrido completo están en el comentario de la constante.
  **Es el cambio eficiente de los dos: 2,3 dB menos de ruido por 0,12 dB de voz (19:1).**
- **δ (`_MCRA_DELTA`) deja de ser constante y escala con la ventana** (property `_mcra_delta`). Era
  1.67 fijo, pero el ratio S_f/S_min **con ruido puro** vale 1,40 a 250 ms y 1,65 a 800 ms — o sea
  que en el default el umbral estaba prácticamente SOBRE la media del ruido y el 41 % de los bins se
  declaraba habla sin que nadie hablara. Peor: **el slider "Reactividad del piso" movía en silencio
  la tasa de falsos positivos entre 20 % y 43 %**, un segundo efecto que nadie decidió. Ahora es
  ~16-18 % constante. Property y no valor cacheado, por el mismo motivo que `_mcra_warmup`.
- **Resultado combinado**, con un cambio REAL de +10 dB de ruido durante la transmisión: ruido
  colado en los huecos **−33,4 → −36,4 dB** (el techo alcanzable es −36,6), voz conservada
  **−2,69 → −3,14 dB**. O sea **3,0 dB de ruido por 0,45 dB de voz**. Sin cambio de ruido el costo
  de voz cae a 0,10 dB. CPU sin cambio (172,9 vs 175,4 µs/frame, medido en el mismo proceso —
  medirlo en procesos distintos daba +14 µs de pura varianza).
- **El costo de voz NO es un defecto**: λ_d ahora sí sigue la subida de ruido, así que el Wiener
  resta más y algo de voz se va con eso. Antes conservaba más voz sólo porque subestimaba el ruido.
- **El margen de δ se eligió por barrido, y el óptimo no fue el primero que probé.** Con margen 1.50
  la mejora de ruido era 0,2 dB mayor pero costaba 0,21 dB más de voz **y triplicaba la deriva de
  λ_d ante un impulso aislado** (0,032 → 0,125 dB). 1.25 se queda con el 93 % del beneficio sin esa
  regresión. Regla: el objetivo era que los falsos positivos dejaran de depender del slider, no
  minimizarlos — pasarse de rosca se paga en voz y en inmunidad a impulsos.
- **DESCARTADO por medición: dejar que los frames con voz alimenten λ_d con un α lento** (~2 s) en
  los bins marcados como ruido, en vez de descartarlos. Da −1,6 dB (peor que el −0,7 de base) y sólo
  1,8 dB en los huecos. **Falla estructuralmente**: el gate `S_f/S_min` no distingue "subió el
  ruido" de "hay voz" — durante el salto S_min va atrasado, el ratio sube y los bins quedan marcados
  como habla justo cuando querías que actualizaran. Es la misma trampa del freeze por vp. No
  reintentarlo por ese camino.
- **Trampa de medición propia, anotada**: la primera pasada usó una voz **puramente periódica y sin
  pausas** y reportó 0-10 % de frames alimentando y λ_d sin seguir nada. Con voz realista (con
  fricativas, que rompen la periodicidad) el mismo escenario da 25 % y sigue el salto. El problema
  era **un tercio** de lo medido. Es la regla de "validar con voz con envolvente" vista al revés:
  una señal demasiado limpia da un falso MAL resultado, no sólo un falso OK.
- **Test flaky descubierto de paso.** `impulso +20dB aislado: drift < 0.2 dB` usaba **una sola
  semilla** de ruido fluctuante: sobre 12 semillas la deriva va de 0,02 a 0,47 dB y **3 de esas 12
  ya violaban el límite antes de tocar nada**. Pasaba por lotería. Ahora promedia 8 semillas
  (~0,18 dB estable, límite 0,35). Guard nuevo además: que la tasa de falsos positivos de I_min con
  ruido puro **no difiera más de 8 puntos entre los extremos del slider** — si alguien vuelve a fijar
  δ, ese check se rompe.
- El indicador S/N pasa de ~7,0 a **6,4 dB** con voz: λ_d está menos sesgado, así que el indicador
  es más preciso (el sobreestimado de ~1,5 dB documentado se achica). No mueve las bandas del manual.

**v2.2 publicada (agosto 2026)** — release en GitHub con distribuibles Windows y Linux. Versión de
app 2.2.0, manuales `MANUAL_RadioNoiseKiller_v2.2.pdf` (ES, 41 págs) y `..._v2.2_EN.pdf` (EN, 40
págs). Título "v2.2 by LU6APA". **Salto de menor**: no cambia el significado de ningún control, pero
sí **cómo se comportan dos detectores**, y en los dos casos el cambio libera valores que antes había
que evitar:
- El **ANF** dejó de tomar armónicos de la voz por heterodinos (persistencia temporal), así que la
  Profundidad ya se puede subir a 90–100 % — el consejo viejo de mantenerla baja era el síntoma de
  un defecto, no una propiedad del filtro. Los presets de fábrica se reajustaron con eso.
- El **supresor de impulsos** compara contra el audio vecino en vez de contra el piso de ruido, así
  que dejó de comprimir la voz. Quien lo tenía apagado por eso puede volver a activarlo.

Los nueve bloques que siguen son el detalle de esta versión. Todo validado en el aire salvo lo que
diga lo contrario. Además: cascada en **modo Diferencia**, botón de donación (Cafecito) en el
"Acerca de", diagnóstico del hilo DSP con `errores_dsp.log` documentado en los manuales, y el
**Nivelador de voz agregado al diagrama del pipeline** (cerró el pendiente que esperaba justamente
un cambio de manual para no regenerar las imágenes y los PDFs dos veces).

**v2.2 — el fallo del hilo procesador era mudo — y no se recuperaba.** Reportado en el aire:
*"cuando arranca en modo MCRA no genera el piso de ruido; la única forma es pasar a Perfil estático
y volver a MCRA"*, con las tres cosas fallando a la vez (no calibra, no reduce, no dibuja el piso) y
después **se arregló solo** sin saber por qué. No se pudo reproducir en el banco: se probaron cuatro
arranques en MCRA, incluido el `settings.json` real del usuario (`block_size` 960, ventana 500 ms) y
con señal con voz — todos calibran.
- **Firma del invariante 9.** Una excepción en `_run_processor` se recupera sola, así que el error
  vuelve cada vez que el estado corrupto se vuelve a tocar; el manejador resetea el profiler y MCRA
  no sale del warmup. Cambiar de modo lo cura porque `set_mode` rearma todo — de ahí el misterio.
- **Causa raíz del "no se recupera": `reset()` no rearmaba las curvas por-bin si el hop no había
  cambiado.** El manejador de errores llama a `reset()` justo para reparar el estado, pero
  `_floor_curve`/`_hf_boost_curve` sólo se reconstruían dentro del `if hop != self._hop`, así que
  una curva con el tamaño viejo **sobrevivía al reset** y el error se repetía para siempre. Ahora se
  rearman también cuando su tamaño no coincide con `_nb`. Verificado: con una curva corrupta
  inyectada, el pipeline da 1 error y se recupera solo (antes quedaba en warmup indefinidamente).
  **Regla: el reset de recuperación tiene que poder reparar el estado que causó el error; si sólo
  limpia buffers, el fallo se vuelve permanente.**
- **Y era invisible.** Tres defectos en el camino de reporte: (1) el callback de error lo invoca el
  **hilo procesador** y llamaba directo a `showMessage()` — tocar widgets fuera del hilo de la GUI es
  comportamiento indefinido en Qt; ahora sólo guarda el texto y lo pinta `_tick_levels`. (2) El
  mensaje era transitorio y lo pisaba el timer de 500 ms con "calibrando (~200 ms)…", que es
  exactamente la mentira que hizo indescifrable el síntoma — ahora el aviso retiene el cartel unos
  segundos (`_dsp_error_hold`). (3) No había contador ni rastro: `pipeline.dsp_error_count` /
  `dsp_last_error`, y el traceback va a **`errores_dsp.log`** en la carpeta de datos, acotado a
  `_DSP_LOG_MAX=5` por sesión. Si vuelve a pasar, el archivo dice qué línea falló.
- **El error NO es por frame**: la línea que falla vive después del warmup, así que sale ~1 por ciclo
  de warmup (≈1/s). Un aviso condicionado a "más de un error por tick" no lo habría mostrado.
- Tests: `test_pipeline` (cuenta, loguea, acota el log y **se recupera solo**) y `test_ui` (el aviso
  se ve y el timer de 500 ms no lo pisa, con el cartel volviendo a la normalidad después).
- **Pendiente:** la causa que corrompió la curva en la máquina del usuario sigue sin identificarse.
  El log es la herramienta para la próxima vez.

**v2.2 — DESCARTADO por medición: criba armónica contra el splatter de SSB.** El usuario
preguntó si había algo de DSP para el splatter (productos de IMD de un vecino sobreexcitado). El
cancelador no lo toca por diseño —es voz, no ruido estacionario, y el min-tracking del MCRA nunca lo
mete en el piso—, así que se prototipó una **criba armónica**: detectar el f0 del corresponsal y
atenuar los bins ENTRE sus armónicos (el inverso del refuerzo de pitch, que los protege).
- **Resultado: +0,6 dB de mejora de la relación señal/interferencia. La vara acordada era 6 dB.** El
  número no se mueve con NADA: bloque 480/960/1920, sigma 0,5–2,5, profundidad 6–30 dB, suavizado
  0–0,7, SIR de entrada 0–12 dB, f0 separados (110 vs 170) o casi iguales (110 vs 115). Cada perilla
  baja el splatter y la voz buena en la misma proporción. Encima cuesta 1,7–2,2 dB de daño a la voz,
  que sí es audible como timbre hueco.
- **Por qué falla, y es estructural:** el splatter es más fuerte justo en los huecos entre las sílabas
  del corresponsal, y ahí la criba está obligada a abrirse porque no hay pitch al cual engancharse.
  Mientras el corresponsal habla, su propia voz ya enmascara al vecino. El peine discrimina bien
  (contiene 56% de la energía de la voz buena contra 5,8% del splatter) — pero sólo sirve donde no
  hace falta.
- **Tres hipótesis propias descartadas por medición en el camino** (vale registrarlas para no
  repetirlas): NO era la entonación (con f0 fijo da igual), NO era el detector de pitch y NO era el
  suavizado temporal de la máscara.
- **Hallazgo aprovechable: el detector de pitch FUNCIONA sobre la mezcla** — 92% de los frames sonoros
  con 2,2 Hz de error mediano, con el vecino a 6 dB de SIR. Habilita una idea que quedó sin medir: un
  gate que cierre en los huecos gobernado por la **periodicidad del corresponsal** en vez de por
  energía (el squelch actual usa el VAD de energía, que toma al splatter por voz y no cierra nunca).
- **Método:** el banco se validó con una **máscara oráculo** que espía las fuentes limpias — da
  +33,6 dB, así que el problema es separable y el instrumento mide bien. **Sin ese control no se puede
  distinguir "la idea no sirve" de "el banco está roto"**, y en este caso los primeros números fueron
  todos ~0 dB por un bug propio (reusar `_harmonic_mask`, cuya sigma de 1.5 bins está pensada para
  PROTEGER armónicos: con bloque 480 la máscara vale 1,00 de media y la criba no hace literalmente
  nada). Regla: **al evaluar una separación de fuentes, medir primero el techo teórico con una máscara
  oráculo.**
- Decisión del usuario: no implementarlo y documentar en el manual que contra el splatter lo que sirve
  es el **pasabanda angostado del lado por el que entra** (Cap. 5 de ambos manuales, con el aviso de no
  bajar de 2,4 kHz y la explicación de por qué parte del splatter es co-canal e infiltrable).

**v2.2 — el ANF tomaba armónicos de la voz por heterodinos.** Detectado por el usuario mirando
los **marcadores de heterodino de la cascada** (feature agregada post-v2.0): *"se ven muchas marcas
rojas que parecen tener relación con la voz, porque si desactivo el ANF no se escucha nada extra"*.
Los marcadores hicieron visible un defecto que llevaba ahí desde siempre.
- **Causa:** el criterio de detección era puramente **instantáneo** — `mag[k] > umbral · mediana(bins
  vecinos)`. Un armónico de voz sobresale de la mediana local exactamente igual que una portadora.
- **Medido con voz sola y NINGÚN heterodino presente** (umbral 3.0, el default): marcaba bins en el
  **100 % de los frames** (15,8 bins/frame con hop 960; 4,8 con hop 480 — peor con más resolución,
  porque los armónicos destacan más). Daño a la voz: **−2,03 dB** con profundidad 0,4 y hop 480,
  **−8,41 dB** con profundidad 0,9 y hop 960.
- **Esto explica de una vez la vieja nota "los valores altos de Profundidad opacan la voz"** (que
  motivó bajar el default de 0.9 a 0.5 en la v1.7): no era un efecto colateral difuso, era el ANF
  notcheando la voz. La guía se reescribió en manuales, tooltip, nota de la UI y `config.py`.
- **Fix — persistencia temporal:** un bin tiene que venir destacando `_PERSIST_MS = 350` ms para
  tratarse como tono. Lo que separa un heterodino de un armónico es el TIEMPO, no el espectro: la
  portadora se queda clavada en el mismo bin durante segundos, el armónico se mueve con la entonación
  y se apaga entre sílabas. La racha tolera **±1 bin** para que un heterodino que deriva no reinicie
  la cuenta. `notched_bins` y `tone_freqs` reportan los tonos CONFIRMADOS, así que los marcadores de
  la cascada pasan a ser fiables.
- **Resultado medido:** falsos positivos **100 % → 0 %**, daño a la voz **−8,41 → −0,00 dB**, y el
  heterodino real se sigue cancelando **−17,9 dB** con **+0,00 dB** de daño colateral. Barrido de
  persistencia: 100 ms deja 50 % de falsos positivos, 200 ms deja 15 %, 400 ms deja 0 % conservando
  95 % de detección. El precio es ~0,4 s para enganchar un tono nuevo — irrelevante en algo estable.
- **La persistencia va en frames → depende del hop** y se recalcula en `_init_ola` (invariante 9);
  `reset()` limpia la racha (si no, tras reiniciar el stream un bin notchearía desde el primer frame).
- Test permanente en `test_dsp`: voz con entonación y envolvente silábica (sin entonación el test
  sería optimista — los armónicos no se moverían), exige <5 % de frames marcados y <0,5 dB de daño,
  que el heterodino real se siga cancelando, y el escalado de la persistencia por hop.
- **Lección de método: un feature de diagnóstico paga solo.** Los marcadores de la cascada se
  agregaron para ver heterodinos, y lo que destaparon fue un bug de años en el módulo que los
  detecta. Cuando algo del DSP se hace visible, se descubre que no hacía lo que decía.
- **VALIDADO en el aire:** *"ahora funciona, ya no aparecen esas marcas rojas con la voz"*. Los
  marcadores de la cascada quedan como indicador fiable de heterodinos reales.
- Caso teórico que no apareció ni en el banco ni en el aire, anotado por si alguna vez se reporta:
  una vocal sostenida y monótona de más de 350 ms podría confirmarse como tono. La entonación real
  lo descarta.
- **Consecuencia práctica — CERRADA (agosto 2026), y confirmó el fix.** Con los falsos positivos en
  cero, el consejo de mantener baja la Profundidad dejó de aplicar (era el síntoma del bug). El
  usuario reajustó los presets escuchando y el punto de operación se movió **en las dos direcciones
  que el fix predecía**: más **profundidad** (`anf_depth` 0.25→0.60 en AM Local, 0.50→0.90 en AM SW
  Ruido Alto; el resto ya en 0.75–1.00) y **umbral más sensible** (`anf_threshold` 3.0→2.0). Lo
  segundo es lo interesante: ahora se puede bajar el umbral espectral porque quien discrimina
  heterodino de armónico es la **persistencia temporal**, no el umbral. Antes bajarlo multiplicaba
  los falsos positivos.

**v2.2 — warmup de MCRA extendido a una ventana completa (B*M).** Reportado en el aire: *"no
anda el MCRA ni muestra la curva amarilla"*, y a los pocos segundos **se corrigió solo**. Con la app
corriendo se verificó que **NO había `errores_dsp.log`** — o sea que no era una excepción del hilo
procesador, que era toda la hipótesis anterior. Descartada.
- **Lo que sí se midió:** con **voz continua** MCRA acumula **2 frames en 20 s** (473 con ruido solo)
  — el freeze por voz haciendo lo suyo — y la exención de warmup terminaba en `_mcra_frames >= M`,
  que con **bloque 1920 es M = 2**. El estimador se declaraba calibrado con dos frames.
- **Cambio:** el warmup pasa a `_MCRA_B * _mcra_M` (ventana completa de mínimos), vía la property
  `_mcra_warmup` para que las **seis** comparaciones no puedan desincronizarse. `_mcra_sub_count >=
  _mcra_M` NO se toca: ahí M sigue significando "frames por subtrama". Warmup medido ~0,40 s en
  bloque 480 y 1920 (antes 0,12 y 0,20 s).
- **HONESTIDAD SOBRE EL RESULTADO: no se pudo demostrar que esto arregle el síntoma.** Midiendo el
  error del piso estimado al activar con voz continua, el comportamiento viejo daba **+0,9 dB
  (bloque 480) y −0,6 dB (1920)** — o sea, ya era bueno. La explicación que se había dado ("arranca
  con un piso construido sobre voz, que es basura") **no quedó confirmada por la medición**. El
  cambio se conserva porque declararse listo con 2 frames es indefendible y hace mentir a
  `has_profile`/`mcra_ready`, pero **la causa del síntoma sigue sin identificarse**.
- El test de errores del DSP en `test_pipeline` pasó de 40 a 140 frames: la línea que falla vive
  después del warmup, y con el warmup más largo 40 frames ya no llegaban — el test se ponía verde
  **sin ejercitar nada**. Ojo con ese patrón al tocar tiempos de warmup.

**v2.2 — el supresor de impulsos destrozaba la voz.** Reportado en el aire: *"el supresor de
impulsos causa una distorsión de la voz, es notoria al activarlo o no"*. Medido sobre voz **limpia y
sin un solo impulso presente**: atenuaba el **26,5 %** de los mini-frames, **−6,8 dB** de voz y
**−6,6 dB de distorsión** (casi el 50 % de la señal). Y el error **empeoraba cuanto mejor era la
señal** (−8,2 dB a S/N 30), que es lo que delató el diseño.
- **Dos causas.** (1) El umbral se comparaba contra el **piso de ruido** (`mini_e > k · energy_hist`):
  con voz 20 dB sobre el piso, la energía de voz es 100× el piso contra un umbral de 12×, así que
  toda sílaba lo cruzaba. No suprimía impulsos: **comprimía la voz** a 12 veces el nivel de ruido con
  ataque de 0,67 ms y sin release. (2) La ganancia se aplicaba como **escalón rectangular cada 32
  muestras**, sin crossfade — cada salto es un click de banda ancha.
- **Rediseño en `src/dsp/blanker.py`** (`ImpulseBlanker`, extraído de `pipeline._run_processor`):
  detección por **contraste local en el tiempo** — mediana de los mini-frames vecinos (~22 ms), el
  mismo principio que usa el ANF en frecuencia. La voz es sostenida, así que sus vecinos están igual
  de fuertes y el cociente da ~1.
- **Resultado medido** (bloque 1920, umbrales 20/12): sobre voz limpia **26,5 % → 0,21 %** de
  disparos, voz **−6,8 → −0,75 dB**, distorsión **−6,6 → −19,3 dB**. Con impulsos reales, la voz pasa
  de **−6,6 a −0,78 dB**. **Precio: la supresión del impulso baja de −20,3 a −13,6 dB.**
- **NO se alcanzó la vara que me había puesto** (distorsión bajo −30 dB): quedó en −19 dB. Los
  disparos que restan son **mini-frames aislados con contraste de 100×**, y el umbral **no los
  separa** — de 8× a 30× el resultado no se mueve. Se acepta porque el problema reportado era la
  distorsión sobre voz y ahí la mejora es de 13 dB.
- **Cuatro errores propios en el camino, cada uno medido y corregido** (valen como patrones):
  1. **Rampa más ancha que el impulso**: con 64 muestras de suavizado, la corrección de un click de
     0,3 ms se diluía y la supresión caía a −0,5 dB. *El filtro que mata el click de la corrección se
     comía también la corrección.* Rampa corta (16) + dilatación de la máscara.
  2. **Falta de `min(gain, 1.0)`**: al dilatar, los vecinos no son impulsos y `sqrt(thr·med/e)` les
     daba ganancia **> 1** — amplificaba el impulso **+12,9 dB**. *Un supresor nunca puede subir nada.*
  3. **Objetivo mal elegido**: atenuar hasta `umbral × mediana` deja el impulso 12 veces sobre sus
     vecinos (−11,9 dB cuando hacían falta −22). En la etapa **mini** el objetivo es el **nivel
     local**; en la etapa de **trama** sí es recortar al umbral, porque con 40 ms por trama la
     mediana de un segundo mezcla sílabas y silencios y bajar a la mediana es un compresor brutal
     (−2,5 dB de voz con 0,2 % de disparos).
  4. **Convolución con retardo**: `mode="valid"` con la cola prepuesta retrasa la ganancia
     `_RAMP−1` muestras, así que la atenuación llegaba **después** del impulso (−3,7 dB). Suavizado
     de **fase cero**: historia a la izquierda, relleno a la derecha.
- **Descartado y anotado:** exigir que el impulso sea breve (descartar rachas de más de 2
  mini-frames, para no tocar ataques de sílaba). No movió ninguna cifra —los falsos disparos ya son
  mini-frames aislados— y además habría excluido las descargas de QRN reales, que duran varios
  mini-frames. No reintentarlo.
- Test permanente en `test_dsp` (disparos, daño, distorsión, supresión de impulso real, y que
  **nunca amplifique**).
- **VALIDADO en el aire, completo** (confirmado al cerrar la v2.2): banda limpia sin distorsión
  —el síntoma reportado— y también con QRN real de descargas, donde pesaba el precio del rediseño
  (la supresión del impulso bajó de −20,3 a −13,6 dB). Si alguna vez suprime de menos, la perilla
  a mover es el umbral mini hacia abajo; el margen está en el detector, no en la rampa.

**v2.2 — "el estimador adaptativo no completa la calibración" — CUARTA rama, sin causa
identificada.** El diagnóstico agregado antes hizo su trabajo: el usuario reportó exactamente el
mensaje de "ninguna de las causas conocidas", lo que **descarta de una** las tres que sí se pueden
ver desde afuera (excepción del hilo procesador, cancelador desactivado, falta de audio).
- **Lo que se descartó leyendo código, sin éxito:** `process()` del profiler corre SIEMPRE (no está
  detrás de `_noise_enabled`), así que `_mcra_frames` debería avanzar; `_mcra_feed` se llama
  incondicionalmente en modo mcra; y los dos `config.dsp.noise_mode = "static"` sueltos de
  `main_window` van después de `set_noise_profile_data`, que ya sincroniza ambos lados. La hipótesis
  más prometedora era **profiler en `static` con la config en `mcra`** (encaja con todo, incluido que
  el toggle de modo lo cure), pero no se encontró ningún camino que produzca esa divergencia.
- **Se dejó de adivinar y se instrumentó.** `pipeline.mcra_diag` expone el estado interno
  (modo de config vs modo del DSP, `noise_enabled`, learning, `_mcra_frames`, `_mcra_warmup`, `M`,
  cuarentena, `voice_hold`, fading, si `λ_d` existe, hop vs block de config, `db_in`, errores) y
  `log_diagnostic()` lo vuelca a `errores_dsp.log`. La cuarta rama lo escribe **una vez por
  episodio** (`_mcra_stall_logged`, reseteado al calibrar). El mensaje ahora pide mandar el archivo.
- **Van cuatro intentos de diagnóstico fallidos sobre este mismo síntoma.** La lección es de método:
  cuando dos rondas de lectura de código no dan, instrumentar sale más barato que una tercera
  hipótesis. Lo mismo valió para el bug del ANF, que sólo apareció cuando los marcadores lo hicieron
  visible.
- Test en `test_ui`: la rama desconocida vuelca exactamente una vez.

**v2.2 — la ganancia A/B de bypass ahora persiste.** Reportado: *"con o sin bypass se usa el
mismo nivel"*. El mecanismo A/B **funcionaba** —verificado manejando la UI: los dos slots guardan y
restauran bien— pero **arrancaba con los dos slots en el mismo valor**, así que en cada arranque se
volvía a "el mismo nivel en los dos modos" hasta ajustar de cada lado. Con una tanda de reinicios
(la de esa sesión), la función nunca llegaba a servir.
- `GainConfig.output_gain_db_bypass` nuevo, persistido en settings.json. Los slots se inicializan
  desde ahí y `_save_settings` los usa como **fuente de verdad**: `set_output_gain_db` del pipeline
  escribe `config.gain.output_gain_db` con el valor del modo ACTUAL, así que sin esa sincronización
  guardar mezclaría el nivel de bypass con el de procesado.
- **No va al preset, a propósito:** un preset describe cómo procesás, no a qué volumen escuchás la
  señal cruda — y como `_capture` ya incluye `output_gain_db`, si viajara, cargar un preset pisaría
  la calibración A/B. Cargar un preset resetea el slot de procesado y **conserva** el de bypass.
- `test_presets::test_capture_covers_all_gain_fields` (el guard del invariante 10) **saltó solo** al
  agregar el campo. Se le puso una lista explícita de exclusiones con su motivo, y además chequea a
  la inversa: que los excluidos NO aparezcan en el preset. El guard sigue cubriendo campos futuros.
- Test en `test_ui`: roundtrip por settings.json y recuperación en una sesión nueva.

**v2.2 — cascada en modo Diferencia (entrada − salida).** Pedido del usuario: *"ver del lado
derecho la entrada y del izquierdo la salida para tener una comparativa visual"*. Se evaluó la vista
doble y se descartó **por dos costos concretos**: con el ancho de ventana FIJO en 770 px cada panel
queda con ~300 px de gráfico (contra ~700), y sobre todo **se rompe la alineación del eje X con el
espectro de arriba**, que es el invariante de diseño de `_ML`/`_MR` y la razón por la que la escala
de color vive en el margen superior. En su lugar se agregó una tercera opción al combo de fuente que
pinta directamente **cuánto quita el procesamiento en cada frecuencia y momento** — misma pregunta,
un solo panel, sin perder resolución ni alineación, y sin comparar dos imágenes a ojo.
- Escala **divergente y FIJA en ±30 dB** (`DIFF_SPAN`), deliberadamente **independiente del slider
  Máx Y**: ese controla un techo de nivel en dBFS y acá los valores son diferencias. `_scale()` es el
  único lugar donde se decide valor→color y lo comparten la cascada y la barra de escala, así no se
  pueden desincronizar. La mitad positiva reusa la rampa SDR (se lee igual que en Entrada/Salida) y
  la negativa usa violeta/magenta, un color que NO aparece en la rampa de nivel — así "se amplificó"
  no se puede confundir con "mucha reducción".
- **El relleno del buffer vacío depende del modo** (`_empty_value`): 0 en diferencia, `DB_MIN` en
  nivel. Con el relleno de nivel, una cascada vacía cae en el extremo "amplificado a full" y se
  pinta entera de magenta.
- **`_compute_db` dejó de clipear a [−80, 0]**; el clip lo hacen ahora los dos llamadores para las
  curvas. Si se resta con ambos lados recortados, **la supresión profunda desaparece**: entrada y
  salida chocan contra el mismo piso y la diferencia da ~0. Medido en el test: con 80 dB de
  supresión real, la versión con clip reporta 48 dB. Las curvas del espectro no cambian.
- Honestidad de lo que muestra: la diferencia incluye **toda la cadena**, no solo el cancelador — la
  ganancia de salida aparece como un tinte violeta parejo (en Bypass se ve exactamente eso y nada
  más, que sirve de verificación de que uno está leyendo bien la escala). Documentado en el tooltip
  y en los manuales ES+EN en vez de "corregirlo" restando el offset: normalizar escondería
  información real.
- `waterfall_source` pasa a aceptar `"diff"` (validación en `config.py`, es `WindowConfig` → **no
  toca presets**, así que no aplica el invariante 10). Test en `test_ui::test_waterfall_diff_mode`:
  persistencia del combo, escala fija ante `set_db_max`, la resta real sin recorte, que no se empuje
  fila con una sola fuente disponible, y **renderizado a QPixmap comprobando el color** (cálido /
  violeta / fondo) — la misma técnica de los marcadores de heterodino.
- **VALIDADO en el aire** (revisión visual del usuario, agosto 2026). `DIFF_SPAN=30` queda como
  rango bueno; si alguna vez satura en rojo o se ve apagado, es la única perilla a mover.

**v2.2 — botón de donación en "Acerca de" (Cafecito).** `_DONATE_URL` en `main_window.py` →
`https://cafecito.app/gpagliaroli`. **Con la constante vacía el botón no se agrega**: así un
placeholder no puede viajar en un release hacia una página rota — mantener ese guard si se toca.
La URL va también en el tooltip porque si `QDesktopServices.openUrl` falla (xdg-open mal
configurado en algún Linux) el botón no haría nada visible. Test en `test_ui` cubre las dos ramas.
- Se descartó **PayPal**: la forma `donate/?business=` con email expondría el correo en un repo
  público (usar el ID de comerciante si alguna vez se vuelve), y sobre todo las restricciones
  históricas de PayPal Argentina para **recibir**. Cafecito cobra ~5% local y ~4,8% + USD 0,35 en
  pagos del exterior (opt-in desde el panel, ya habilitado), liquidando en pesos al oficial.
- El "Acerca de" **no estaba documentado en ningún manual**; se aprovechó para describirlo entero
  (versión, build id, autor, repo) además del botón. Badge de Cafecito en el README, variante
  `button_6` (celeste) elegida porque el negro se pierde contra el fondo oscuro de GitHub.
- **VALIDADO por el usuario**: botón clickeado en la app real y badge del README revisado en las
  dos temáticas.
- **Tres presets de fábrica reajustados en la misma tanda** (ver [[project_factory_presets]]):
  `AM Local - RuidoMedio`, `AM SW - Ruido Alto y Fading` y `AM SW - Ruido Medio y Fading`. Además
  del ANF (arriba), el patrón es Intensidad más baja (0.7→0.6 en los tres) compensada con
  post-filtro, y el nivelador más rápido (`release_ms` 1000→600 / 500→700). El **techo de ruido del
  AGC quedó desactivado** en los tres — se agregó a `AM Local` (que no lo tenía) directamente en
  false. Verificado que los 7 presets cargan con `matches()==True`, o sea sin "(modificado)"
  espurio; a cuatro les faltan `agc_noise_ceiling_*` y funcionan igual gracias al fix de
  `from_dict` (invariante 10) — **segunda vez que ese fix evita regenerar los presets**.
- **Bug preexistente encontrado de paso y corregido: clave i18n duplicada.** `i18n_en.py` tenía
  `"medio"` dos veces — `"medium"` para el ancho del Q (EQ Voz) y `"mid"` para el centro del boost
  (piso perceptual). **Como la clave del catálogo ES el texto en español, dos etiquetas que dicen lo
  mismo comparten traducción**, y en un dict literal la segunda pisa a la primera en silencio: el
  slider de Q mostraba "mid" en inglés. No se arregla del lado del catálogo; hay que desambiguar el
  español. La etiqueta del centro del boost pasó a **`medios`** (plural), que además es como se dice
  en jerga de audio para las frecuencias medias: `grave / vocal / medios` → `low / vocal / mid`,
  y el Q recupera `wide / medium / narrow`. **Chequeo barato para repetir:** parsear `i18n_en.py`
  con `ast` y contar claves repetidas en el dict — `Counter` sobre `ast.Dict.keys` las encuentra
  todas, y `import` no avisa nada porque el dict se construye igual.

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
- **Es un ajuste POR ESTACIÓN y los presets lo llevan apagado (agosto 2026).** Al reajustar los
  presets el usuario lo dejó desactivado en los tres, con este razonamiento: *"el piso de ruido que
  yo percibo no es el mismo en otro QTH y puede limitar más que ayudar"*. Es correcto y es una
  propiedad del control, no una preferencia: el techo es un nivel **absoluto en dBFS**, mientras que
  el piso depende del QTH, la antena, la banda y la hora. Un preset que viaje con un techo calibrado
  en otra estación puede quedar **por debajo** del piso real del que lo carga → 0 dB de ganancia
  permitida → ahoga la voz débil en vez de mejorarla, y el síntoma no se parece en nada a la causa.
  Manuales ES+EN y el tooltip del slider ahora dicen explícitamente que **no hay un valor
  recomendado** y que se calibra escuchando en la propia estación.
  - **No se lo sacó del preset** (a diferencia de la ganancia A/B de bypass): el campo sigue en
    `_capture`, así que alguien que arma su preset personal se lo lleva, que es lo correcto. Lo que
    cambia es que los **de fábrica** lo traen en `false`.
  - Patrón a tener en cuenta al agregar controles: **un umbral absoluto calibrado contra el entorno
    de RF de una estación no es portable.** Los controles que se expresan en relación a algo medido
    (el piso estimado, el S/N, un porcentaje) sí viajan bien entre estaciones; los que se expresan
    en dBFS absolutos, no. Si aparece otro control así, el default debe ser "desactivado".

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
  **Segundo reporte, mismo patrón, ahora con las palabras:** el tooltip de Protección de armónicos
  decía "Alto…" y la etiqueta muestra `suave/normal/fuerte`. Pasada sobre los 45: 6 reales
  (`_s_pitch_strength`, `_s_leveler_max`, `_s_noise_smooth`, `_s_squelch_threshold`, `_s_pf_boost`
  y `_s_anf_threshold`, que usaba "sensible/selectivo" contra `alta/media/baja`). Chequeo hermano
  del de unidades: barrer cada `SliderRow` de mínimo a máximo, juntar las palabras entre paréntesis
  que muestra la etiqueta, y marcar los tooltips que usan "alto/bajo" teniendo vocabulario propio
  disponible. **El `alto/bajo` sólo es un error cuando la etiqueta ofrece una palabra específica**;
  quedan 9 usos legítimos (frecuencia más alta, orden del armónico, "línea de alta tensión", y los
  controles cuya etiqueta muestra sólo el número).
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
- **`.github/FUNDING.yml` — diferido hasta tener GitHub Sponsors aprobado.** Pondría el botón
  *Sponsor* en la página del repo. Decisión del usuario: esperar a la habilitación de Sponsors para
  listar las dos plataformas juntas, en vez de hacerlo ahora sólo con Cafecito. **No proponerlo
  suelto**; el disparador es que Sponsors quede aprobado (Argentina está entre las regiones
  soportadas; el trámite pide 2FA, Stripe Connect y W-8BEN, y GitHub no cobra comisión).
  Si eso pasa, además hay que ver si el "Acerca de" muestra un botón o dos: hoy `_DONATE_URL` es
  una sola URL y habría que convertirla en una lista de `(etiqueta, url)`.
- Validar build en Pi real (ARM64 Raspberry Pi OS Bookworm)
- Reducir/optimizar el tamaño total de la app. **Primera pasada hecha y validada en ambas
  plataformas (v1.5):** recorte de módulos Qt sin uso en ambos specs (`QT_EXCLUDES` + filtro
  `sin_basura_qt()`) — Windows dist 218→166 MB, artifact Linux 189→~170 MB (con libQt6OpenGL y
  plugins wayland restaurados tras el fix de decoraciones). Sin recorte posible en scipy (los
  imports de scipy.signal arrastran todo transitivamente — verificado) ni en las dos OpenBLAS
  (ABIs distintas). Pendiente si se quiere más: UPX (no está instalado — el `upx=True` de los
  specs hoy es no-op; ojo falsos positivos de antivirus) y re-recortar libQt6OpenGL en Linux
  (bradient usa libGL del sistema, no la lib de Qt)

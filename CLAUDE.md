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

## Empaquetado multiplataforma — invariantes (lecciones v1.4/v1.5)

La app es Python + PySide6 empaquetada con PyInstaller para Windows y Linux. Los bugs de
empaquetado se descubren en el hardware del usuario, no en CI — anticiparlos:

1. **Plugins agregados a mano al spec: rastrear sus DT_NEEDED.** PyInstaller solo recorre
   dependencias binarias de lo que él mismo recolecta. Al agregar un `.so`/`.dll` a `a.binaries`
   después del `Analysis` (como los plugins de decoración Wayland), verificar con pyelftools
   (está en el venv) que TODAS sus DT_NEEDED estén en el bundle o sean libs del sistema —
   un plugin presente pero sin sus dependencias falla silencioso (dlopen) y el síntoma aparece
   solo en runtime en la máquina del usuario.
2. **Audio en Linux: preferir las libs del sistema.** `libasound` y `libportaudio` bundleadas
   (las del runner de CI) no cargan los plugins ALSA/Pulse del host — dispositivos virtuales
   desaparecen. Ambas se excluyen del bundle (ver `reductor-linux.spec`); no revertir.
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
| `tests/test_presets.py` | `_capture()` cubre DSPConfig/GainConfig, roundtrips, rename/delete |
| `tests/test_noise_vad.py` | VAD del squelch (ruido fluctuante, voz armónica, release AGC), cuarentena MCRA, clamps de fading. **Validar detectores con ruido fluctuante y voz con envolvente — el gaussiano estacionario da falsos OK** |
| `tests/test_integration.py` | Pipeline headless (`start(headless=True)`) con TODOS los módulos activos: warmup MCRA, ciclo squelch, cambios de modo en caliente, cambio de block size con reinicio |
| `tests/test_ui.py` | UI offscreen (`QT_QPA_PLATFORM=offscreen` + `MainWindow`): orden de pestañas (Módulos en pos 1), "Módulos activos" en su pestaña, visibilidad de botones de perfiles por modo estático/MCRA, gating de controles Avanzados por módulo (invariante 2), restauración de checkboxes desde config (invariante 8). **SliderRow deshabilita los hijos — testear con `row._slider.isEnabled()`, no `row.isEnabled()`** |

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

Cambios v1.7 (pendiente de release):
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
  campos nuevos). **Pendiente: validación en el aire.**
- **`tests/test_ui.py` permanente** (backlog v1.7): formaliza los tests offscreen de UI que antes
  se hacían a mano cada sesión — la categoría de regresión más frecuente. Ver la tabla de tests.
- **Rolloff del piso perceptual más empinado** (`/6000` → `/2500` en `_build_floor_curve`):
  el usuario reportó que "Profundidad del rolloff" no se notaba entre 0 y −70%. Causa: la rampa
  lineal repartía el efecto sobre 6000 Hz, así que dentro de la banda de voz (SSB 2.7k, AM 4-4.5k)
  la reducción del piso era mínima (−1.3 dB a 4.5k con 55%). Con `/2500` la profundidad plena cae
  cerca del borde de banda → ~2.7× más efecto dentro de banda (−3.5 dB a 4.5k). OJO: en SSB angosto
  con "Inicio del rolloff"=3000 el módulo sigue sin actuar (la banda termina antes de 3000) — la
  nota del slider ahora avisa de bajar el "Inicio" en banda angosta y muestra la atenuación en dB
  (55% ≈ −7 dB). Subir el máximo del slider NO era la solución (el cuello era la pendiente `/6000`,
  no la profundidad). Nota UI reescrita (ES+EN).
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
- ✅ **Preset de fábrica "Voz natural"** (hecho — AM+SSB; falta validación en el aire).
- ✅ **Perfiles de ruido nombrados** (hecho, validado con hardware real).
- ✅ **tests/test_ui.py permanente** (hecho).
- **Waterfall en la pestaña Espectro**: cascada con historia (~30s) además del espectro
  instantáneo — permite VER el QSB, heterodinos intermitentes y QRM. **Único ítem pendiente.**

Pendiente para Fase 2:
- Validar build en Pi real (ARM64 Raspberry Pi OS Bookworm)
- Reducir/optimizar el tamaño total de la app. **Primera pasada hecha y validada en ambas
  plataformas (v1.5):** recorte de módulos Qt sin uso en ambos specs (`QT_EXCLUDES` + filtro
  `sin_basura_qt()`) — Windows dist 218→166 MB, artifact Linux 189→~170 MB (con libQt6OpenGL y
  plugins wayland restaurados tras el fix de decoraciones). Sin recorte posible en scipy (los
  imports de scipy.signal arrastran todo transitivamente — verificado) ni en las dos OpenBLAS
  (ABIs distintas). Pendiente si se quiere más: UPX (no está instalado — el `upx=True` de los
  specs hoy es no-op; ojo falsos positivos de antivirus) y re-recortar libQt6OpenGL en Linux
  (bradient usa libGL del sistema, no la lib de Qt)

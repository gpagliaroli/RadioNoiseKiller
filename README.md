# RadioNoiseKiller

Software standalone de reducción de ruido en tiempo real para radio AM/SSB (ham radio).
Procesa el audio ya demodulado entre el receptor y los parlantes o auriculares.

Todo el DSP es **numpy/scipy puro** — sin IA, sin modelos externos, sin GPU y sin internet.

**Plataformas:** Windows 10/11 · Linux x86_64 · ARM64 / Raspberry Pi (experimental)
**Idiomas:** español · inglés

---

## Descargas

Los paquetes listos para usar están en la [página de releases](https://github.com/gpagliaroli/RadioNoiseKiller/releases/latest):

| Archivo | Para |
|---|---|
| `RadioNoiseKiller_vX.Y.zip` | Windows 10/11 (64 bits) |
| `RadioNoiseKiller_vX.Y-linux-x86_64.zip` | Linux x86_64 |
| `MANUAL_RadioNoiseKiller_vX.Y.pdf` | Manual completo en español |
| `MANUAL_RadioNoiseKiller_vX.Y_EN.pdf` | Manual completo en inglés |

No requieren instalación. **El manual es la documentación de verdad**: este README es sólo el
panorama general y las notas para quien quiera tocar el código.

---

## Características

**Reducción de ruido**

- **Cancelador de ruido estacionario** — estimador decision-directed con ganancia Log-MMSE
  (Ephraim-Malah) y suavizado OMLSA, con anti-gorgojeo automático gateado por el detector de voz
- **Dos modos de estimación** — perfil **estático** aprendido a mano, o **adaptativo (MCRA)** que
  sigue el piso de ruido en continuo sin intervención
- **Post-filtro espectral** — segunda pasada que hunde el piso sólo en los bins de ruido
- **Supresor de impulsos** — dos niveles en cascada (10 ms y 0,67 ms) para QRN atmosférico,
  detectados por contraste contra el audio vecino (no contra el piso), así la voz no dispara
- **ANF** — filtro de muesca espectral adaptativo para heterodinos, portadoras y zumbidos
- **Gate de ruido** — baja el fondo entre transmisiones cuando el nivel de entrada no llega al
  umbral, con cierre progresivo; umbral en dBFS, así se calibra mirando el indicador de nivel

**Nivel y timbre**

- **AGC** — tres velocidades (slow / medium / fast), con **techo de ruido** opcional para que no
  amplifique el ruido de banda cuando la señal es débil
- **Nivelador de voz** — segundo AGC post-cancelador gateado por el detector de voz, para emparejar
  estaciones de niveles dispares; con opción de nivelar en continuo para música
- **Filtro de paso de banda** — por modo (AM / SSB), con la salida configurable independiente de la
  entrada para no apilar dos rolloffs sobre la voz
- **EQ de voz** — presencia (consonantes) y cuerpo (fundamentales), paramétricos
- **Excitador armónico** — genera armónicos reales para recuperar el brillo que cortó la radio, con
  control de carácter par/impar y gate por detección de voz
- **Recuperar graves** — reconstruye el fundamental **derivándolo de los armónicos** que sobrevivieron
  al filtro del receptor, sin sintetizar nada

**Interfaz y operación**

- **Espectro en tiempo real** + **cascada** con historia ajustable (15–120 s), escala de color y
  marcadores de los tonos que está cancelando el ANF
- **Cascada en modo Diferencia** — pinta cuánto quita el procesamiento en cada frecuencia y
  momento, para ver de un vistazo si el cancelador está tocando la voz
- **Presets** — 7 perfiles de fábrica afinados en el aire, más los propios
- **Perfiles de ruido nombrados** — guardar y recuperar el ruido de cada banda o cada hora del día
- **Grabación a WAV** — con opción de grabar en paralelo la entrada sin procesar, para el antes/después
- **Tamaño de interfaz ajustable** (100 / 125 / 150 %) y ayuda contextual en todos los sliders
- **Standalone** — sin instalación de Python, sin internet, sin GPU

---

## Pipeline de procesamiento

![Pipeline de procesamiento](Images/pipeline_diagram.png)

Los módulos opcionales se activan y desactivan en vivo desde la pestaña *Módulos*. El cancelador
tiene además dos sub-módulos que corren dentro de él (refuerzo de pitch y post-filtro espectral).

---

## Uso

1. Conectar la salida de audio del receptor a la entrada de la PC (o usar un cable de audio virtual
   para SDR por software)
2. Seleccionar **dispositivo de entrada** y **salida** — ambos de la misma API de audio
3. Elegir el modo: **AM** o **SSB**
4. Presionar **ACTIVAR**
5. En modo estático, aprender el perfil de ruido: **⏺ Aprender ruido** durante 3–5 segundos sin
   señal, luego **⏹ Detener**. En modo adaptativo no hace falta: calibra solo.

Para Windows: ejecutar `RadioNoiseKiller.exe`
Para Linux: dar permisos y ejecutar:

```bash
chmod +x RadioNoiseKiller
./RadioNoiseKiller
```

---

## Instalación en desarrollo

```bash
git clone https://github.com/gpagliaroli/RadioNoiseKiller.git
cd RadioNoiseKiller

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux

pip install -r requirements.txt
python src/main.py
```

En Windows hay wrappers en la raíz: `run.cmd` (lanza la aplicación) y `test.cmd` (corre los tests).

### Tests

```bash
python tests/run_all.py
```

Corre las 8 suites de regresión headless en subprocesos aislados. Los datos escribibles se redirigen
a una carpeta temporal vía la variable `RNK_DATA_DIR`, así que **los tests nunca tocan tu
`settings.json` ni tus presets**. `test_devices.py` y `test_hostapis.py` quedan fuera del runner:
requieren hardware de audio y son diagnósticos. `test_cpu_profile.py` tampoco, es un benchmark.

### Empaquetar

```bash
# Windows
python -m PyInstaller reductor.spec --clean --noconfirm

# Linux (x86_64 y ARM64 usan el mismo spec)
python -m PyInstaller reductor-linux.spec --clean --noconfirm
```

El build de Linux también corre en GitHub Actions al pushear un tag de versión (`v*`), o a mano desde
la pestaña *Actions*. El disparo manual tiene además la opción de compilar para **ARM64 / Raspberry
Pi**, que por ahora es experimental: compila, pero todavía no se verificó que arranque en una Pi real.

---

## Estructura del proyecto

```
src/
├── main.py               # Entrada: escala de UI → QApplication → MainWindow
├── config.py             # AppConfig (audio, dsp, ganancia, ventana) + save/load JSON
├── pipeline.py           # ProcessingPipeline: orquesta audio I/O + DSP en tiempo real
├── presets.py            # PresetManager: captura/aplica configuraciones completas
├── noise_profiles.py     # NoiseProfileManager: perfiles de ruido nombrados
├── i18n.py / i18n_en.py  # Traducción ES→EN (catálogo propio, sin Qt Linguist)
├── utils.py              # Rutas de recursos y de datos escribibles (RNK_DATA_DIR)
├── buildinfo.py          # BUILD_ID, estampado en el empaquetado
├── audio/
│   ├── devices.py        # Enumeración y deduplicación por API (WASAPI/WDM-KS, ALSA)
│   ├── stream.py         # AudioStream: wrapper de sounddevice con callback
│   └── recorder.py       # WavRecorder: grabación a WAV con hilo escritor propio
├── dsp/
│   ├── noise_profiler.py # Cancelador: DD + Log-MMSE + OMLSA, MCRA, post-filtro, pitch
│   ├── agc.py            # AGC (también usado como nivelador de voz)
│   ├── anf.py            # AdaptiveNotchFilter: heterodinos y tonos
│   ├── filters.py        # BandpassFilter + PresenceFilter (Butterworth / peaking IIR)
│   ├── exciter.py        # AuralExciter: armónicos con carácter par/impar y gate por VAD
│   ├── bass.py           # BassRestorer: fundamental derivado de los armónicos
│   ├── blanker.py        # ImpulseBlanker: impulsos por contraste local en el tiempo
│   ├── gate.py           # NoiseGate: decide con el nivel de entrada, atenúa la salida
│   ├── gain.py           # GainLimiter: limitador de picos con rodilla suave
│   └── level.py          # LevelMeter: RMS con decaimiento
└── ui/
    ├── main_window.py    # Ventana principal: 7 pestañas + barra de estado
    ├── advanced_tab.py   # Pestañas Avanzada Audio / Impulsos / Cancelador
    ├── presets_tab.py    # Gestión de presets
    ├── slider_row.py     # Widget: label + QSlider escalado a float + valor
    ├── tooltips.py       # Textos de ayuda de todos los sliders
    ├── vu_meter.py       # VU meter custom (QPainter)
    ├── spectrum_widget.py# Espectro en tiempo real (FFT + EMA)
    └── waterfall_widget.py # Cascada tiempo-frecuencia

Presets/                  # 7 presets de fábrica (JSON) + Presets.zip
tests/                    # Suites de regresión (run_all.py) y diagnósticos
tools/                    # Generadores del manual PDF, el diagrama y el zip de presets
Images/                   # Logo, ícono y diagramas del pipeline
.github/workflows/        # Build de Linux (x86_64 y ARM64) en Actions
```

---

## Dependencias

| Paquete | Uso |
|---------|-----|
| `sounddevice` | Audio I/O vía PortAudio |
| `numpy` | Procesamiento numérico |
| `scipy` | Filtros IIR, FFT y funciones especiales |
| `PySide6` | Interfaz gráfica (Qt6) |
| `pyinstaller` | Empaquetado standalone (sólo desarrollo) |

---

## Notas para operadores de radio

- **SDR por software**: usar *Mezcla estéreo* (Stereo Mix) como entrada para capturar el audio de
  SDR#, HDSDR, etc. sin cable físico
- **Entrada y salida de la misma API**: PortAudio no puede combinar, por ejemplo, una entrada WASAPI
  con una salida WDM-KS. La aplicación lo detecta y avisa antes de dejar arrancar
- **Aprender ruido**: correrse un poco en frecuencia a un hueco **sin emisoras** antes de aprender.
  Si entra voz o una portadora, queda horneada en el perfil y el cancelador la resta como si fuera
  ruido
- **Calibrar la Intensidad con el Preview**: subirla mientras lo que se elimina sea sólo ruido, y
  bajar un paso donde empiece a filtrarse voz
- **Receta recomendada**: Intensidad baja (50–60 %) + Post-Filtro alto. Da mejor cancelación y voz
  más natural que subir la Intensidad sola
- **Gate de ruido**: poner el umbral entre el nivel que marca el indicador en los huecos y el que
  marca con señal. Es un ajuste de cada estación: no hay un valor recomendado
- **Bypass**: compara la señal con y sin procesamiento en vivo, y recuerda la ganancia de salida por
  separado en cada estado para que la comparación sea a nivel parejo

El manual desarrolla todo esto con mucho más detalle, incluido un capítulo de flujo de calibración
recomendado.

---

## Autor

**Germán Pagliaroli — LU6APA**

## Apoyar el proyecto

RadioNoiseKiller es gratuito y de código abierto, y va a seguir siéndolo. Si te resultó
útil en el aire y querés bancar el desarrollo, podés invitarme un café:

[![Invitame un café en cafecito.app](https://cdn.cafecito.app/imgs/buttons/button_6.png)](https://cafecito.app/gpagliaroli)

La donación es completamente opcional y no habilita ninguna función.
*(Cafecito acepta tarjetas internacionales — International cards are accepted.)*

## Licencia

MIT — ver [LICENSE](LICENSE).

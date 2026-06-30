# Reductor de Ruido Radio

Software standalone de reducción de ruido en tiempo real para señales de radio AM y SSB (ham radio), usando inteligencia artificial. Funciona con la placa de sonido de la PC como entrada y salida.

---

## Características

- **Reducción de ruido con IA**: modelo DeepFilterNet3 corriendo localmente vía ONNX Runtime (sin GPU, sin internet)
- **Tiempo real**: latencia total ~40–80 ms, adecuada para monitoreo
- **Modos de radio**: AM, SSB-USB y SSB-LSB con filtros bandpass específicos por modo
- **Standalone**: ejecutable `.exe` sin necesidad de instalar Python
- **Configuración persistente**: todos los parámetros se guardan en `settings.json`
- **Pestaña Avanzada**: control fino de filtros, ganancia y parámetros del modelo mediante sliders

---

## Capturas

```
┌─────────────────────────────────────────────┐
│  Reductor de Ruido Radio  v0.1              │
│  [ Principal ] [ Avanzada ]                 │
├─────────────────────────────────────────────┤
│ Dispositivos de Audio                       │
│  Entrada: [ Micrófono (Logi) [WASAPI] ▼ ]  │
│  Salida:  [ Altavoces (Realtek) [WASAPI] ▼ ]│
├─────────────────────────────────────────────┤
│ Control                                     │
│  Modo:       [ SSB-USB ▼ ]                  │
│  Supresión:  ●──────────────────○  75%      │
│  □ Bypass (sin procesamiento IA)            │
├─────────────────────────────────────────────┤
│ Niveles                                     │
│  IN  ████████░░░░░░░░  -12 dB               │
│  OUT ██████░░░░░░░░░░  -15 dB               │
│                         Latencia: 42 ms     │
├─────────────────────────────────────────────┤
│  [ ▶ ACTIVAR ]                              │
└─────────────────────────────────────────────┘
```

---

## Requisitos

- **SO**: Windows 10/11 (64-bit) — Linux en planificación (Fase 2)
- **CPU**: cualquier CPU de 2+ núcleos (sin GPU requerida)
- **RAM**: ~500 MB en uso
- **Audio**: placa de sonido con entrada de línea o micrófono

---

## Instalación y uso (ejecutable)

1. Descargar y descomprimir la carpeta `ReductorRuidoRadio/`
2. Ejecutar `ReductorRuidoRadio.exe`
3. Seleccionar dispositivos de entrada y salida de audio
4. Elegir el modo de radio (AM / SSB-USB / SSB-LSB)
5. Ajustar el slider de Supresión
6. Presionar **ACTIVAR**

> La primera vez tarda ~3–5 segundos en cargar el modelo IA antes de habilitar el botón ACTIVAR.

---

## Instalación en desarrollo

### Prerrequisitos

- Python 3.11+ (recomendado 3.11 o 3.12 para mayor compatibilidad de paquetes)
- Git

### Pasos

```bash
git clone <repo>
cd Reductor_Ruido_Radio

# Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar
python src/main.py
```

> **Nota**: el paquete `deepfilternet` de PyPI requiere Rust/Cargo para compilar.
> Este proyecto usa los modelos ONNX pre-exportados directamente (en `models/`),
> evitando esa dependencia. No instalar `deepfilternet` por pip.

### Empaquetar en .exe

```bash
python -m PyInstaller reductor.spec --clean --noconfirm
# Resultado en dist/ReductorRuidoRadio/
```

---

## Arquitectura

```
src/
├── main.py              # Punto de entrada (QApplication)
├── config.py            # Dataclasses de configuración + save/load JSON
├── pipeline.py          # Orquestador del flujo de audio en tiempo real
├── utils.py             # resource_path() y settings_path() para bundle PyInstaller
│
├── audio/
│   ├── devices.py       # Enumeración de dispositivos (deduplicada por API: WASAPI > WDM-KS)
│   └── stream.py        # AudioStream: callback de sounddevice en tiempo real
│
├── dsp/
│   ├── filters.py       # BandpassFilter: Butterworth IIR por modo (AM/SSB-USB/SSB-LSB)
│   ├── gain.py          # GainLimiter: ganancia + peak limiter de ataque instantáneo
│   └── level.py         # LevelMeter: RMS con decaimiento para VU meter
│
├── models/
│   └── deepfilternet.py # Wrapper ONNX Runtime para DeepFilterNet3
│
└── ui/
    ├── main_window.py   # Ventana principal con QTabWidget
    ├── advanced_tab.py  # Pestaña Avanzada con sliders de configuración
    ├── slider_row.py    # Widget reutilizable: label + QSlider + valor
    └── vu_meter.py      # Widget VU meter con gradiente verde→amarillo→rojo
```

### Flujo de procesamiento

```
[Placa de sonido - Entrada]  48kHz, mono, float32
        │
        ▼
[InputGain]               Ganancia de entrada en dB (live)
        │
        ▼
[BandpassFilter]          Butterworth IIR orden 4
        │                 AM:  300–3400 Hz
        │                 SSB: 200–3000 Hz  (ajustable en pestaña Avanzada)
        ▼
[DeepFilterNet3]          Inferencia ONNX: enc → erb_dec → df_dec
        │                 Ventana: 10 frames × 10ms = 100ms
        │                 Latencia algorítmica: ~40ms
        ▼
[GainLimiter]             Ganancia de salida + peak limiter (-1 dBFS por defecto)
        │
        ▼
[Placa de sonido - Salida]
```

### Modelo IA: DeepFilterNet3

El modelo se divide en tres redes ONNX:

| Archivo | Rol | Tamaño |
|---------|-----|--------|
| `models/enc.onnx` | Encoder: extrae embeddings del espectrograma | 1.9 MB |
| `models/erb_dec.onnx` | Decoder ERB: genera máscara espectral | 3.1 MB |
| `models/df_dec.onnx` | Decoder DF: coeficientes de filtrado profundo | 3.2 MB |

Parámetros internos del modelo (de `models/config.ini`):

| Parámetro | Valor |
|-----------|-------|
| Sample rate | 48000 Hz |
| FFT size | 960 muestras |
| Hop size | 480 muestras (10 ms) |
| Bandas ERB | 32 |
| Bins DF | 96 |

### Gestión de dispositivos de audio

En Windows, PortAudio expone el mismo dispositivo físico bajo cuatro APIs (MME, DirectSound, WASAPI, WDM-KS). El módulo `audio/devices.py` deduplica la lista mostrando solo:
- **WASAPI** (prioridad, menor latencia)
- **WDM-KS** para dispositivos sin equivalente WASAPI (ej: *Mezcla estéreo*, útil para capturar audio de software SDR)

---

## Configuración avanzada

La pestaña **Avanzada** expone los siguientes parámetros mediante sliders:

### Audio *(requiere reiniciar el procesamiento)*

| Parámetro | Rango | Default | Descripción |
|-----------|-------|---------|-------------|
| Tamaño de bloque | 240–1920 muestras | 480 (10 ms) | Buffer de audio. Menor = menor latencia, más CPU |

### Filtros DSP *(en tiempo real)*

| Parámetro | Rango | Descripción |
|-----------|-------|-------------|
| AM – Hz inferior | 50–1000 Hz | Corte bajo del bandpass en modo AM |
| AM – Hz superior | 1000–6000 Hz | Corte alto del bandpass en modo AM |
| SSB-USB/LSB – Hz inferior | 50–1000 Hz | Corte bajo en modos SSB |
| SSB-USB/LSB – Hz superior | 1000–6000 Hz | Corte alto en modos SSB |
| Orden del filtro | 2 / 4 / 6 / 8 | Mayor orden = corte más abrupto, más CPU |

### Modelo IA *(requiere reiniciar el procesamiento)*

| Parámetro | Rango | Default | Descripción |
|-----------|-------|---------|-------------|
| Ventana de proceso | 5–30 frames | 10 (100 ms) | Mayor ventana = mejor calidad, mayor latencia |

### Ganancia *(en tiempo real)*

| Parámetro | Rango | Default | Descripción |
|-----------|-------|---------|-------------|
| Ganancia entrada | -20 a +20 dB | 0 dB | Amplificación antes del filtro y del modelo |
| Ganancia salida | -20 a +20 dB | 0 dB | Amplificación después del modelo |
| Límite de picos | -20 a 0 dBFS | -1 dBFS | Techo del peak limiter de salida |

---

## Persistencia de configuración

Al cerrar la aplicación (o con debounce de 800 ms al cambiar valores), se guarda `settings.json` en:

- **Ejecutable standalone**: junto al `.exe` en `dist/ReductorRuidoRadio/settings.json`
- **Desarrollo**: raíz del proyecto `settings.json`

---

## Dependencias principales

| Paquete | Versión | Uso |
|---------|---------|-----|
| `sounddevice` | ≥0.5.5 | Audio I/O via PortAudio |
| `numpy` | ≥2.0 | Procesamiento numérico |
| `scipy` | ≥1.13 | Filtros IIR (Butterworth) |
| `onnxruntime` | ≥1.18 | Inferencia del modelo IA |
| `PySide6` | ≥6.7 | Interfaz gráfica (Qt6) |
| `pyinstaller` | ≥6.8 | Empaquetado standalone |

---

## Notas para operadores de radio

- **Conexión**: conectar la salida de audio del receptor al Line-In de la placa de sonido, y la salida de la aplicación a los auriculares/altavoces
- **SDR software**: usar el dispositivo *Mezcla estéreo* (Stereo Mix / What U Hear) como entrada para capturar el audio de SDR# u otro software SDR sin cable físico
- **Modo Bypass**: permite comparar la señal con y sin procesamiento manteniendo el ruteo de audio activo
- **Ajuste de ganancia**: si la señal de entrada es débil, subir la Ganancia de entrada antes que el volumen del receptor para optimizar la relación señal/ruido que ve el modelo
- **SSB-USB vs SSB-LSB**: el procesamiento de audio es idéntico en ambos modos; la diferencia está en las frecuencias de corte del bandpass que se pueden ajustar independientemente

---

## Roadmap

### Fase 1 ✅ (actual)
- Pipeline completo AM/SSB en tiempo real
- UI con pestañas Principal y Avanzada
- Ejecutable Windows standalone

### Fase 2 (planificada)
- Visualizador de espectro en tiempo real (antes/después)
- Integración completa del filtrado profundo (`df_dec`)
- Soporte Linux (PipeWire/ALSA)
- Packaging Linux (AppImage)

---

## Licencia

Los modelos de DeepFilterNet3 están bajo licencia **MIT**.
El código de este proyecto está bajo licencia **MIT**.

# RadioNoiseKiller

Software standalone de reducción de ruido en tiempo real para radio AM/SSB (ham radio).
Procesa el audio ya demodulado entre el receptor y los parlantes/auriculares.

**Plataformas:** Windows 10/11 · Linux (build automático vía GitHub Actions)

---

## Características

- **Cancelador de ruido estacionario** — estimador DD Wiener con suavizado OMLSA: ancla bins de ruido al floor evitando el gorgojeo (musical noise)
- **Supresor de impulsos** — dos niveles en cascada (10ms y 0,67ms) para QRN atmosférico
- **ANF** — filtro de muesca espectral adaptativo para heterodinos y portadoras AM
- **AGC** — control automático de ganancia (slow / medium / fast / custom con target, ganancia máx, ataque y release ajustables)
- **Squelch de voz** — silencia la salida entre transmisiones SSB, con hold time configurable
- **EQ de presencia** — realce de consonantes en la zona de legibilidad
- **Excitador armónico** — genera armónicos en 1–4 kHz para recuperar brillo post-filtrado
- **Filtro de paso de banda** — independiente pre y post cancelador, por modo (AM / SSB)
- **Standalone** — sin instalación de Python, sin internet, sin GPU

---

## Pipeline de procesamiento

```
Audio entrada (48kHz, mono, float32)
  → Ganancia de entrada
  → Supresor de impulsos (frame 10ms + mini-frame 0,67ms)
  → AGC
  → Filtro de paso de banda PRE  (opcional)
  → ANF — Filtro de muesca espectral
  → Cancelador de ruido DD Wiener + OMLSA
  → Squelch de voz  (opcional)
  → Filtro de paso de banda POST (opcional)
  → EQ de presencia
  → Excitador armónico  (opcional)
  → GainLimiter
Audio salida
```

---

## Uso

1. Conectar la salida de audio del receptor a la entrada de la PC (o usar un cable de audio virtual para SDR por software)
2. Seleccionar **dispositivo de entrada** y **salida** en la aplicación
3. Elegir el modo: **AM** o **SSB**
4. Presionar **ACTIVAR**
5. Aprender el perfil de ruido: pulsar **⏺ Aprender ruido** durante 3–5 segundos sin señal, luego **⏹ Detener**

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

### Empaquetar

```bash
# Windows
python -m PyInstaller reductor.spec --clean --noconfirm

# Linux
python -m PyInstaller reductor-linux.spec --clean --noconfirm
```

El build de Linux también corre en GitHub Actions al pushear un tag de versión (`v*`), o a mano desde
la pestaña *Actions*. El disparo manual tiene además la opción de compilar para **ARM64 / Raspberry
Pi**, que por ahora es experimental: compila, pero todavía no se verificó que arranque en una Pi real.

---

## Estructura del proyecto

```
src/
├── main.py              # Entrada: QApplication → MainWindow
├── config.py            # AppConfig — dataclasses + save/load JSON
├── pipeline.py          # Orquestador del flujo DSP en tiempo real
├── utils.py             # resource_path() y settings_path()
├── audio/
│   ├── devices.py       # Enumeración multiplataforma (WASAPI/WDM-KS en Windows, ALSA/PulseAudio en Linux)
│   └── stream.py        # AudioStream: callback sounddevice
├── dsp/
│   ├── noise_profiler.py# DD Wiener + OMLSA + OLA
│   ├── anf.py           # Filtro de muesca espectral adaptativo
│   ├── filters.py       # BandpassFilter (Butterworth IIR) + PresenceFilter (peaking EQ)
│   ├── exciter.py       # AuralExciter (tanh + HPF 1kHz)
│   ├── gain.py          # GainLimiter (peak follower)
│   ├── level.py         # LevelMeter (RMS con decaimiento)
│   └── agc.py           # Control automático de ganancia
└── ui/
    ├── main_window.py   # Ventana principal con tabs
    ├── advanced_tab.py  # Tabs Avanzada Audio y Avanzada Ruido
    ├── slider_row.py    # Widget label + QSlider + unidad
    └── vu_meter.py      # VU meter custom (QPainter)
```

---

## Dependencias

| Paquete | Uso |
|---------|-----|
| `sounddevice` | Audio I/O via PortAudio |
| `numpy` | Procesamiento numérico |
| `scipy` | Filtros IIR (Butterworth, biquad) |
| `PySide6` | Interfaz gráfica (Qt6) |
| `pyinstaller` | Empaquetado standalone |

---

## Notas para operadores de radio

- **SDR software**: usar *Mezcla estéreo* (Stereo Mix) como entrada para capturar el audio de SDR#, HDSDR, etc. sin cable físico
- **Squelch**: solo para transmisiones de voz SSB/AM — no usar con música (produce bombeo)
- **Aprender ruido**: hacerlo cuando la estación no transmite para capturar el ruido real de la banda
- **Bypass**: permite comparar la señal con y sin procesamiento en tiempo real

---

## Licencia

MIT

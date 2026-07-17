# -*- coding: utf-8 -*-
"""
Catálogo español → inglés. La clave es el texto fuente EXACTO que aparece
en el código (ver i18n.py). Mantener los placeholders {x} y los prefijos
(↳, ⏺, ⏹, ↺) idénticos a la clave.

Para regenerar la lista de claves: scratchpad/extract_keys.py sobre src/ui/*.py.
Una clave ausente no rompe nada — el texto sale en español.
"""

CATALOG = {
    # --- Ventana principal / pestañas ---
    "Listo. Presiona ACTIVAR para iniciar.": "Ready. Press START to begin.",
    "Principal": "Main",
    "Avanzada Audio": "Advanced Audio",
    "Avanzada Impulsos": "Advanced Impulse",
    "Avanzada Cancelador": "Advanced Canceller",
    "Espectro": "Spectrum",
    "Presets": "Presets",

    # --- Dispositivos ---
    "Dispositivos de Audio": "Audio Devices",
    "Entrada:": "Input:",
    "Salida:": "Output:",
    "Volver a buscar dispositivos de audio (hardware conectado o\n"
    "desconectado con la aplicación abierta). Requiere procesamiento detenido.":
        "Rescan audio devices (hardware plugged or unplugged\n"
        "while the application is open). Requires processing stopped.",
    "Error al re-enumerar dispositivos: {e}": "Error rescanning devices: {e}",
    "Canal:": "Channel:",
    "Izquierdo": "Left",
    "Derecho": "Right",
    "Mezcla L+R": "L+R mix",
    "Canal tomado de entradas estéreo. Útil si la radio entrega el audio\n"
    "por el canal derecho, o para elegir receptor en radios con doble RX\n"
    "(principal=izquierdo, sub=derecho). Se aplica en vivo.":
        "Channel taken from stereo inputs. Useful when the radio delivers audio\n"
        "on the right channel, or to pick a receiver on dual-RX radios\n"
        "(main=left, sub=right). Applies live.",
    "Dispositivos actualizados: {n} de entrada, {m} de salida.":
        "Devices updated: {n} input, {m} output.",

    # --- Control ---
    "Control": "Control",
    "Modo:": "Mode:",
    "AGC:": "AGC:",
    "Desactivado": "Off",
    "Rápido": "Fast",
    "Medio": "Medium",
    "Lento": "Slow",
    "Bypass (sin procesamiento)": "Bypass (no processing)",
    "Idioma de la interfaz — requiere reiniciar la aplicación":
        "Interface language — requires restarting the application",
    "Idioma guardado — reiniciar la aplicación para aplicarlo.":
        "Language saved — restart the application to apply it.",
    "▶  ACTIVAR": "▶  START",
    "⏹  DETENER": "⏹  STOP",
    "Procesando...": "Processing...",
    "Detenido.": "Stopped.",

    # --- Módulos activos ---
    "Módulos activos": "Active Modules",
    "Supresor de impulsos": "Impulse suppressor",
    "Elimina QRN, frituras y descargas atmosféricas cortas.":
        "Removes QRN, crackle and short atmospheric discharges.",
    "Filtro de paso de banda  (pre)": "Bandpass filter  (pre)",
    "Butterworth IIR antes del cancelador de ruido — limita el espectro que aprende el perfil.":
        "Butterworth IIR before the noise canceller — limits the spectrum the profile learns.",
    "Filtro de paso de banda  (post)": "Bandpass filter  (post)",
    "Butterworth IIR después del cancelador de ruido — elimina fugas espectrales del STFT.":
        "Butterworth IIR after the noise canceller — removes STFT spectral leakage.",
    "ANF — Cancela heterodinos y tonos interferentes":
        "ANF — Removes heterodynes and interfering tones",
    "Detecta bins espectrales que sobresalen sobre el ruido vecino y los atenúa.":
        "Detects spectral bins standing out above neighboring noise and attenuates them.",
    "Cancelador de ruido estacionario": "Stationary noise canceller",
    "Filtro de Wiener espectral. Requiere perfil aprendido.":
        "Spectral Wiener filter. Requires a learned profile.",
    "Piso espectral perceptual  (curva de enmascaramiento auditivo)":
        "Perceptual spectral floor  (auditory masking curve)",
    "Reemplaza el floor fijo por una curva que varía por frecuencia:\n"
    "  · +75% en ~500 Hz (fundamentales vocales, preserva la calidez)\n"
    "  · Neutro en 1000–3000 Hz (formantes, sin cambio)\n"
    "  · –55% sobre 3 kHz (ruido de alta frecuencia, suprime más)\n"
    "El slider 'Piso espectral' de Avanzada Ruido controla el nivel global.\n"
    "Requiere cancelador activo.":
        "Replaces the fixed floor with a frequency-dependent curve:\n"
        "  · +75% at ~500 Hz (vocal fundamentals, preserves warmth)\n"
        "  · Neutral at 1000–3000 Hz (formants, unchanged)\n"
        "  · –55% above 3 kHz (high-frequency noise, suppressed harder)\n"
        "The 'Spectral floor' slider in Advanced Canceller sets the global level.\n"
        "Requires the canceller enabled.",
    "Post-filtro espectral  (ruido musical residual)":
        "Spectral post-filter  (residual musical noise)",
    "Segunda pasada sobre bins de ruido para eliminar el 'ruido musical'\n"
    "(pitidos intermitentes) que deja el Wiener. Requiere cancelador activo.\n"
    "Agresividad configurable en pestaña Avanzada Ruido.":
        "Second pass over noise bins to remove the 'musical noise'\n"
        "(intermittent birdies) the Wiener filter leaves behind. Requires the canceller enabled.\n"
        "Aggressiveness adjustable in the Advanced Canceller tab.",
    "Refuerzo de pitch de voz  (detección por autocorrelación)":
        "Voice pitch enhancement  (autocorrelation detection)",
    "Detecta el tono fundamental de la voz y protege sus armónicos\n"
    "del cancelador de ruido. Mejora la inteligibilidad de señales de voz\n"
    "débiles enterradas en ruido, tanto en AM como en SSB.\n"
    "Sensibilidad configurable en pestaña Avanzada Ruido.":
        "Detects the fundamental pitch of the voice and protects its harmonics\n"
        "from the noise canceller. Improves intelligibility of weak voice\n"
        "signals buried in noise, on both AM and SSB.\n"
        "Sensitivity adjustable in the Advanced Canceller tab.",
    "Squelch de voz  (con música no utilizar!)": "Voice squelch  (do not use with music!)",
    "Silencia la salida cuando no hay voz detectada. Requiere perfil de ruido aprendido.":
        "Mutes the output when no voice is detected. Requires a learned noise profile.",
    "Compensación fading HF  (onda corta con QSB)": "HF fading compensation  (shortwave QSB)",
    "Congela el estimador de ruido durante fades ionosféricos y acelera\n"
    "la recuperación al volver la señal. Solo tiene efecto en modo Adaptativo (MCRA).\n"
    "Sensibilidad y duración del freeze configurables en Avanzada Cancelador.":
        "Freezes the noise estimator during ionospheric fades and speeds up\n"
        "recovery when the signal returns. Only effective in Adaptive (MCRA) mode.\n"
        "Sensitivity and freeze duration adjustable in Advanced Canceller.",
    "Nivelador de voz  (compensa condiciones de banda)":
        "Voice leveler  (compensates band conditions)",
    "AGC de voz después del cancelador: mantiene la voz limpia a nivel\n"
    "constante aunque el ruido (y por ende la cancelación) varíe.\n"
    "Solo adapta cuando detecta voz — el ruido residual entre\n"
    "transmisiones no se re-amplifica. Requiere cancelador activo.":
        "Voice AGC after the canceller: keeps the clean voice at a constant\n"
        "level even as noise (and thus cancellation) varies.\n"
        "Only adapts while voice is detected — residual noise between\n"
        "transmissions is not re-amplified. Requires the canceller enabled.",
    "EQ Voz  (presencia + cuerpo)": "Voice EQ  (presence + body)",
    "Dos picos de realce vocal configurables en pestaña Avanzada Audio:\n"
    "  · Presencia (1000–2000 Hz): claridad e inteligibilidad\n"
    "  · Cuerpo (150–800 Hz): calidez y graves de la voz\n"
    "Cada banda con ganancia 0 dB queda en passthrough.":
        "Two vocal peaking EQs adjustable in the Advanced Audio tab:\n"
        "  · Presence (1000–2000 Hz): clarity and intelligibility\n"
        "  · Body (150–800 Hz): warmth and low end of the voice\n"
        "Each band at 0 dB gain is exact passthrough.",
    "Excitador armónico": "Harmonic exciter",
    "Genera armónicos en 1–4 kHz para recuperar presencia y ataque de consonantes.":
        "Generates 1–4 kHz harmonics to restore presence and consonant attack.",

    # --- Cancelación de ruido (grupo Principal) ---
    "Cancelación de Ruido Estacionario": "Stationary Noise Cancellation",
    "Perfil estático": "Static profile",
    "Adaptativo (MCRA)": "Adaptive (MCRA)",
    "Perfil estático: aprendizaje manual de 5s.\n"
    "Adaptativo (MCRA): estima el ruido automáticamente en tiempo real,\n"
    "  se adapta a cambios de banda sin intervención del usuario.":
        "Static profile: manual 5-second learning.\n"
        "Adaptive (MCRA): estimates noise automatically in real time,\n"
        "  adapts to band changes without user intervention.",
    "⏺  Aprender ruido": "⏺  Learn noise",
    "Borrar perfil": "Clear profile",
    "💾  Guardar perfil...": "💾  Save profile...",
    "Guarda el perfil de ruido actual con un nombre, para reutilizarlo\n"
    "sin volver a aprenderlo (p. ej. \"40m casa\", \"20m campo\").":
        "Saves the current noise profile under a name, to reuse it\n"
        "without learning it again (e.g. \"40m home\", \"20m field\").",
    "📁  Perfiles...": "📁  Profiles...",
    "Cargar, renombrar o eliminar perfiles de ruido guardados.":
        "Load, rename or delete saved noise profiles.",
    "Guardar perfil de ruido": "Save noise profile",
    "Nombre del perfil:": "Profile name:",
    "Ya existe un perfil llamado '{name}'.\n\nDeseas reemplazarlo?":
        "A profile named '{name}' already exists.\n\nReplace it?",
    "Perfil de ruido \"{name}\" guardado.": "Noise profile \"{name}\" saved.",
    "Perfiles de ruido": "Noise profiles",
    "Cargar perfil:": "Load profile:",
    "Error al cargar el perfil": "Error loading the profile",
    "Perfil de ruido \"{name}\" cargado.": "Noise profile \"{name}\" loaded.",
    "Perfil de ruido \"{name}\" cargado. Listo para ACTIVAR.":
        "Noise profile \"{name}\" loaded. Ready to START.",
    "Intensidad:": "Intensity:",
    "Reducción activa:": "Active reduction:",
    "Preview: escuchar ruido eliminado": "Preview: listen to removed noise",
    "Emite el ruido que está siendo restado.\nSi suena como voz, bajar la Intensidad.":
        "Plays the noise being subtracted.\nIf it sounds like voice, lower the Intensity.",
    "Sin perfil — activar procesamiento y presionar Aprender":
        "No profile — start processing and press Learn",
    "Sin perfil — presionar Aprender para calibrar":
        "No profile — press Learn to calibrate",
    "Perfil activo: {dur:.1f}s aprendidos — sustracción ON":
        "Active profile: {dur:.1f}s learned — subtraction ON",
    "⏹  Aprendiendo... {s}s": "⏹  Learning... {s}s",
    "Aprendiendo ruido — mantener silencio en la banda":
        "Learning noise — keep the band silent",
    "Adaptativo (MCRA) — activar procesamiento para calibrar":
        "Adaptive (MCRA) — start processing to calibrate",
    "Adaptativo (MCRA) — estimando en tiempo real":
        "Adaptive (MCRA) — estimating in real time",
    "Adaptativo (MCRA) — calibrando (~200ms)...":
        "Adaptive (MCRA) — calibrating (~200ms)...",
    "~0 dB  (sin ruido detectable)": "~0 dB  (no detectable noise)",

    # --- Grabación a WAV ---
    "⏺  Grabar": "⏺  Record",
    "⏹  Detener grabación": "⏹  Stop recording",
    "Graba la salida procesada a un archivo WAV (16-bit, 48 kHz)\n"
    "en la carpeta Grabaciones/, junto al ejecutable.\n"
    "Disponible con el procesamiento activo.":
        "Records the processed output to a WAV file (16-bit, 48 kHz)\n"
        "in the Grabaciones/ folder, next to the executable.\n"
        "Available while processing is active.",
    "incluir entrada sin procesar": "include unprocessed input",
    "Graba además un segundo WAV con la señal de entrada tal como\n"
    "llega de la radio — para comparar el antes/después.\n"
    "Se aplica al iniciar la próxima grabación.":
        "Also records a second WAV with the input signal as it\n"
        "arrives from the radio — for before/after comparison.\n"
        "Applies when the next recording starts.",
    "Error al iniciar la grabación: {e}": "Error starting the recording: {e}",
    "Grabando en Grabaciones/ ...": "Recording to Grabaciones/ ...",
    "Grabación guardada en Grabaciones/  ({s:.0f} s)":
        "Recording saved to Grabaciones/  ({s:.0f} s)",
    "Error de grabación: {e}": "Recording error: {e}",

    # --- Niveles y ganancia ---
    "Niveles y Ganancia": "Levels & Gain",
    "Latencia: --": "Latency: --",
    "Latencia: {ms:.0f} ms": "Latency: {ms:.0f} ms",
    "Límite de picos:": "Peak limit:",
    "Limitador de picos:": "Peak limiter:",
    "Nivelador de voz:": "Voice leveler:",
    "ACTIVO  {db:.1f} dB": "ACTIVE  {db:.1f} dB",

    # --- Espectro ---
    "Entrada": "Input",
    "Salida": "Output",
    "Lo cancelado": "Cancelled",
    "Piso de ruido": "Noise floor",
    "Relación señal/ruido de banda completa (suavizada ~1s):\n"
    "señal actual vs piso de ruido estimado por el cancelador.\n"
    "Con solo ruido marca ~0 dB.":
        "Full-band signal-to-noise ratio (smoothed ~1s):\n"
        "current signal vs the canceller's estimated noise floor.\n"
        "With noise only it reads ~0 dB.",
    "Máx Y:": "Max Y:",
    "Máx X:": "Max X:",
    "Activar el procesamiento para ver el espectro":
        "Start processing to see the spectrum",

    # --- Avanzada Audio ---
    "↺  Restaurar valores por defecto": "↺  Restore defaults",
    "Audio": "Audio",
    "Tamaño de bloque:": "Block size:",
    "{n} muestras ({ms:.0f} ms)": "{n} samples ({ms:.0f} ms)",
    "  ↳ Menor = menor latencia. Requiere reiniciar el procesamiento.":
        "  ↳ Smaller = lower latency. Requires restarting processing.",
    "AGC Personalizado  (activar con AGC: Custom en Principal)":
        "Custom AGC  (enable with AGC: Custom in Main)",
    "Nivel objetivo:": "Target level:",
    "bajo": "low",
    "normal": "normal",
    "alto": "high",
    "  ↳ Nivel RMS al que el AGC lleva la señal. -20 dBFS=default, más alto=más fuerte.":
        "  ↳ RMS level the AGC drives the signal to. -20 dBFS=default, higher=louder.",
    "Ganancia máxima:": "Max gain:",
    "limitado": "limited",
    "máximo": "maximum",
    "  ↳ Tope de amplificación en señales débiles. Bajo=no levanta el ruido de fondo.":
        "  ↳ Amplification cap for weak signals. Low=doesn't raise the noise floor.",
    "Ataque:": "Attack:",
    "rápido": "fast",
    "lento": "slow",
    "  ↳ Cuán rápido baja la ganancia ante señal fuerte. Rápido=protege, puede bombear.":
        "  ↳ How fast gain drops on strong signals. Fast=protective, may pump.",
    "Release:": "Release:",
    "  ↳ Cuán rápido recupera ganancia al caer la señal. Lento=estable en QSB, rápido=sigue el fading.":
        "  ↳ How fast gain recovers when the signal drops. Slow=stable in QSB, fast=tracks the fading.",
    "Filtro de paso de banda  (pre y post — en tiempo real)":
        "Bandpass filter  (pre & post — real time)",
    "AM – Hz inferior:": "AM – low Hz:",
    "AM – Hz superior:": "AM – high Hz:",
    "SSB – Hz inferior:": "SSB – low Hz:",
    "SSB – Hz superior:": "SSB – high Hz:",
    "Orden del filtro:": "Filter order:",
    "Orden {n}": "Order {n}",
    "Salida independiente de la entrada": "Output independent from input",
    "Con la casilla apagada, el filtro de salida usa los mismos límites que\n"
    "el de entrada (comportamiento clásico). Activada, la salida tiene sus\n"
    "propios límites: permite entrada angosta (menos soplido al cancelador)\n"
    "con salida más ancha (la voz no se recorta dos veces en el borde).":
        "With the box unchecked, the output filter uses the same limits as\n"
        "the input one (classic behavior). Checked, the output has its own\n"
        "limits: allows a narrow input (less hiss into the canceller) with\n"
        "a wider output (the voice is not clipped twice at the band edge).",
    "AM salida – Hz inferior:": "AM output – low Hz:",
    "AM salida – Hz superior:": "AM output – high Hz:",
    "SSB salida – Hz inferior:": "SSB output – low Hz:",
    "SSB salida – Hz superior:": "SSB output – high Hz:",
    "  ↳ Consejo: entrada angosta (p. ej. SSB hasta 2700 Hz) + salida más ancha "
    "(3500–4000 Hz) conserva el borde superior de la voz y el brillo del excitador.":
        "  ↳ Tip: narrow input (e.g. SSB up to 2700 Hz) + wider output "
        "(3500–4000 Hz) preserves the upper edge of the voice and the exciter's brightness.",
    "Frecuencia de cuerpo:": "Body frequency:",
    "grave": "low",
    "cuerpo": "body",
    "calidez": "warmth",
    "Cuerpo (ganancia):": "Body (gain):",
    "  ↳ Refuerza los graves de la voz (fundamentales). 0 dB=apagado, +3–5 dB=voz con más cuerpo.":
        "  ↳ Boosts the low end of the voice (fundamentals). 0 dB=off, +3–5 dB=fuller voice.",
    "Frecuencia de presencia:": "Presence frequency:",
    "media-baja": "low-mid",
    "media": "mid",
    "presencia": "presence",
    "Presencia (ganancia):": "Presence (gain):",
    "  ↳ Frecuencia + ganancia del pico vocal. 0 dB=neutro, +4–6 dB=voz de radio.":
        "  ↳ Frequency + gain of the vocal peak. 0 dB=neutral, +4–6 dB=radio voice.",
    "Ancho de presencia (Q):": "Presence width (Q):",
    "  ↳ Q bajo = boost ancho (más cálido), Q alto = pico estrecho (más nasal).":
        "  ↳ Low Q = wide boost (warmer), high Q = narrow peak (more nasal).",
    "Corrección de tono SSB:": "SSB pitch correction:",
    "neutro": "neutral",
    "agudo": "high",
    "  ↳ Corrige offset de BFO en SSB. +100 Hz si la voz suena grave, -100 Hz si suena aguda.":
        "  ↳ Corrects SSB BFO offset. +100 Hz if the voice sounds low, -100 Hz if it sounds high.",
    "Excitador armónico  (se aplica en tiempo real)": "Harmonic exciter  (applied in real time)",
    "Drive:": "Drive:",
    "suave": "soft",
    "agresivo": "aggressive",
    "  ↳ Saturación tanh: cuántos armónicos se generan. Bajo=sutil, alto=efecto notable.":
        "  ↳ Tanh saturation: how many harmonics are generated. Low=subtle, high=pronounced.",
    "Mezcla:": "Mix:",
    "  ↳ Nivel de armónicos mezclados. 20–40% = zona útil sin sonar artificial.":
        "  ↳ Level of harmonics mixed in. 20–40% = useful range without sounding artificial.",

    # --- Avanzada Impulsos ---
    "Supresor de impulsos  (se aplica en tiempo real)": "Impulse suppressor  (applied in real time)",
    "Actividad:": "Activity:",
    "Umbral de trama (10 ms):": "Frame threshold (10 ms):",
    "  ↳ Bajo=captura más impulsos (QRN fuerte). Alto=solo blancos muy grandes.":
        "  ↳ Low=catches more impulses (heavy QRN). High=only very large hits.",
    "Umbral micro (0.67 ms):": "Micro threshold (0.67 ms):",
    "  ↳ Detecta frituras y crackles cortos. Bajo=elimina más, puede recortar consonantes.":
        "  ↳ Catches short crackle and static. Low=removes more, may clip consonants.",
    "Sensibilidad:": "Sensitivity:",
    "alta": "high",
    "baja": "low",
    "  ↳ Ratio bin/baseline para detectar un tono. Bajar si hay tonos débiles.":
        "  ↳ Bin/baseline ratio to detect a tone. Lower it for weak tones.",
    "Profundidad:": "Depth:",
    "  ↳ Atenuación aplicada al tono detectado. 100%=silencia, 50%=reduce 6dB.":
        "  ↳ Attenuation applied to the detected tone. 100%=silences, 50%=reduces 6 dB.",
    "tono": "tone",
    "tonos": "tones",

    # --- Avanzada Cancelador ---
    "Cancelador de ruido estacionario  (Wiener Log-MMSE)":
        "Stationary noise canceller  (Log-MMSE Wiener)",
    "Reducción:": "Reduction:",
    "Voz:": "Voice:",
    "Piso espectral:": "Spectral floor:",
    "  ↳ Ganancia mínima por bin. 0.10=suprime 20dB (recomendado). Mínimo 0.05.":
        "  ↳ Minimum per-bin gain. 0.10=20 dB suppression (recommended). Minimum 0.05.",
    "Anti-gorgojeo (β):": "Anti-warble (β):",
    "reactivo": "reactive",
    "  ↳ Release (retorno al ruido), pasos de 0.1% para calibrar fino. 99%≈1s de release — puede dejar cola de ruido tras la voz.":
        "  ↳ Release (return to noise), 0.1% steps for fine tuning. 99%≈1s release — may leave a noise tail after speech.",
    "Velocidad ataque:": "Attack speed:",
    "  ↳ Attack (onset de voz): bajo=consonantes nítidas. Alto=transiciones suaves.":
        "  ↳ Attack (voice onset): low=crisp consonants. High=smooth transitions.",
    "Compensación fading HF:": "HF fading compensation:",
    "  ↳ Activar en Módulos Activos (sub-módulo del cancelador). Solo modo Adaptativo.":
        "  ↳ Enable in Active Modules (canceller sub-module). Adaptive mode only.",
    "Sensibilidad fading:": "Fading sensitivity:",
    "sensible": "sensitive",
    "selectivo": "selective",
    "  ↳ Cambio de energía que dispara el freeze. Bajo=detecta QSB suave, puede disparar con la voz. Alto=solo fades profundos.":
        "  ↳ Energy change that triggers the freeze. Low=detects mild QSB, may trigger on voice. High=deep fades only.",
    "Duración del freeze:": "Freeze duration:",
    "corto": "short",
    "largo": "long",
    "  ↳ Tiempo que MCRA queda congelado tras cada evento. Fades lentos necesitan más; muy largo desactualiza el piso.":
        "  ↳ How long MCRA stays frozen after each event. Slow fades need more; too long lets the floor go stale.",
    "Squelch de voz  (activar en Módulos Activos)": "Voice squelch  (enable in Active Modules)",
    "Nivel de voz:": "Voice level:",
    "Gate:": "Gate:",
    "  ↳ Ajustar Umbral (%) para que quede entre el nivel en silencio y con voz.":
        "  ↳ Set the Threshold (%) between the silent level and the voice level.",
    "Umbral:": "Threshold:",
    "  ↳ El ruido marca ~0% (el detector exige estructura de voz): 10–25% suele bastar. Subirlo solo si una interferencia tonal abre el gate.":
        "  ↳ Noise reads ~0% (the detector requires voice structure): 10–25% is usually enough. Raise it only if a tonal interference opens the gate.",
    "Retención:": "Hold:",
    "  ↳ Tiempo que el gate permanece abierto tras perder la voz. Default 300 ms.":
        "  ↳ How long the gate stays open after voice is lost. Default 300 ms.",
    "Piso espectral perceptual  (activar en Módulos Activos)":
        "Perceptual spectral floor  (enable in Active Modules)",
    "Piso vocal:": "Vocal floor:",
    "Activo:": "Active:",
    "  ↳ 'Piso vocal': piso en la zona de mayor boost. 'Activo': % bins retenidos ahora.":
        "  ↳ 'Vocal floor': floor at the peak-boost zone. 'Active': % of bins currently held.",
    "Amplitud boost vocal:": "Vocal boost amount:",
    "sin boost": "no boost",
    "fuerte": "strong",
    "  ↳ Cuánto se eleva el piso en la zona vocal. 75%=suave, 150%=normal, 250%=máximo.":
        "  ↳ How much the floor rises in the vocal zone. 75%=soft, 150%=normal, 250%=maximum.",
    "Centro del boost:": "Boost center:",
    "vocal": "vocal",
    "medio": "mid",
    "  ↳ Frecuencia de máximo boost. 500 Hz=AM/SSB típico. 350 Hz=SSB muy grave.":
        "  ↳ Frequency of maximum boost. 500 Hz=typical AM/SSB. 350 Hz=very low SSB voice.",
    "Inicio del rolloff:": "Rolloff start:",
    "pronto": "early",
    "tarde": "late",
    "  ↳ A partir de qué frecuencia baja el piso. 3000 Hz=default.":
        "  ↳ Frequency where the floor starts dropping. 3000 Hz=default.",
    "Profundidad del rolloff:": "Rolloff depth:",
    "sin rolloff": "no rolloff",
    "  ↳ Cuánto cae el piso en altas frecuencias. 55%=default.":
        "  ↳ How much the floor drops at high frequencies. 55%=default.",
    "Post-filtro espectral  (activar en Módulos Activos)":
        "Spectral post-filter  (enable in Active Modules)",
    "Reducción extra:": "Extra reduction:",
    "  ↳ dB extra eliminados en bins de ruido vs cancelador base. 0 dB = sin efecto.":
        "  ↳ Extra dB removed on noise bins vs the base canceller. 0 dB = no effect.",
    "Agresividad:": "Aggressiveness:",
    "desactivado": "off",
    "muy agresivo": "very aggressive",
    "  ↳ Supresión extra en bins de ruido para eliminar 'pitidos fantasma'. 1=moderado, 2=normal, 4+=muy agresivo (vigilar que la voz no se recorte).":
        "  ↳ Extra suppression on noise bins to remove 'ghost birdies'. 1=moderate, 2=normal, 4+=very aggressive (watch for voice clipping).",
    "Refuerzo de pitch de voz  (activar en Módulos Activos)":
        "Voice pitch enhancement  (enable in Active Modules)",
    "Pitch detectado:": "Detected pitch:",
    "  ↳ f0 de la voz en tiempo real. Con voz clara debería marcar 80–400 Hz estable.":
        "  ↳ Voice f0 in real time. With clear voice it should read a stable 80–400 Hz.",
    "Protección de armónicos:": "Harmonic protection:",
    "  ↳ Cuánto eleva la probabilidad de voz en bins de armónicos. 70%=recomendado.":
        "  ↳ How much it raises voice probability on harmonic bins. 70%=recommended.",
    "Nivelador de voz  (activar en Módulos Activos)":
        "Voice leveler  (enable in Active Modules)",
    "  ↳ Tope de compensación para voz débil. Alto=iguala más las señales, pero levanta también el ruido que acompaña a la voz débil.":
        "  ↳ Compensation cap for weak voice. High=evens out signals more, but also raises the noise riding along with the weak voice.",

    # --- Indicadores ---
    "ABIERTO": "OPEN",
    "CERRADO": "CLOSED",
    "—  (desactivado)": "—  (off)",
    "sin perfil": "no profile",
    "0 dB  (sin ruido activo)": "0 dB  (no active noise)",
    "sin detección": "no detection",

    # --- Presets ---
    "Presets guardados:": "Saved presets:",
    "Nombre:": "Name:",
    "Nombre del preset...": "Preset name...",
    "Guardar como nuevo": "Save as new",
    "Sobrescribir seleccionado": "Overwrite selected",
    "Cargar": "Load",
    "Eliminar": "Delete",
    "Renombrar seleccionado": "Rename selected",
    "Preset activo:": "Active preset:",
    "(ninguno)": "(none)",
    "Cargar un preset aplica todos los ajustes DSP y Ganancia\n"
    "en caliente, sin reiniciar el audio.\n"
    "Doble-clic en la lista carga el preset directamente.":
        "Loading a preset applies all DSP and Gain settings\n"
        "on the fly, without restarting audio.\n"
        "Double-click on the list loads the preset directly.",
    "Confirmar reemplazo": "Confirm replace",
    "Ya existe un preset llamado '{name}'.\n\nDeseas reemplazarlo?":
        "A preset named '{name}' already exists.\n\nReplace it?",
    "Error al cargar preset": "Error loading preset",
    "Confirmar eliminacion": "Confirm delete",
    "Eliminar el preset '{name}'?": "Delete preset '{name}'?",
    "Renombrar preset": "Rename preset",
    "Nuevo nombre:": "New name:",
    "Nombre en uso": "Name in use",
    "Ya existe un preset llamado '{name}'.": "A preset named '{name}' already exists.",
    "Error al renombrar": "Error renaming",
    "{name}  (modificado)": "{name}  (modified)",

    # --- Varios ---
    "↺  Restaurar por defecto  ({val})": "↺  Restore default  ({val})",
    "Error: {msg}": "Error: {msg}",
}

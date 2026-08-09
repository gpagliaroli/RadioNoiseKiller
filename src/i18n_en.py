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
    "Módulos": "Modules",
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
    "Acerca de RadioNoiseKiller": "About RadioNoiseKiller",
    "Acerca de": "About",
    "Versión {ver} · build {build}": "Version {ver} · build {build}",
    "Reductor de ruido para radio AM/SSB (ham radio).":
        "Noise reducer for AM/SSB radio (ham radio).",
    "DSP puro numpy/scipy — sin IA ni modelos externos.":
        "Pure numpy/scipy DSP — no AI or external models.",
    "Autor: Germán Pagliaroli": "Author: Germán Pagliaroli",
    "Intensidad:": "Intensity:",
    "Post-Filtro:": "Post-filter:",
    "Hunde el piso de los bins de ruido: cada punto son ~4.5 dB más abajo\n"
    "(el fondo queda más silencioso y parejo, sin 'gorgojeo').\n"
    "0 = apagado. No toca los bins de voz. Se enciende solo al pasar de 0.":
        "Pushes the noise bins' floor down: each point is ~4.5 dB deeper\n"
        "(the background gets quieter and steadier, without 'warble').\n"
        "0 = off. It leaves the speech bins alone. It turns on by itself above 0.",
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
    "📁  Perfil cargado:  «{name}»": "📁  Loaded profile:  «{name}»",
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
    "🔇  Mute": "🔇  Mute",
    "🔇  Silenciado": "🔇  Muted",
    "Silencia la salida a los parlantes sin detener el procesamiento.\n"
    "Útil para una prueba corta: el proceso, la grabación y los\n"
    "medidores siguen corriendo — solo se corta el audio que se escucha.":
        "Mutes the speaker output without stopping processing.\n"
        "Handy for a quick test: processing, recording and the\n"
        "meters keep running — only the audio you hear is cut.",
    "Salida silenciada — el procesamiento sigue activo.":
        "Output muted — processing is still active.",
    "Velocidad de respuesta:": "Response speed:",
    "  ↳ Qué tan rápido sigue el nivelador los cambios de nivel. Rápido = sigue el fading cíclico y rápido; suave = más estable, menos bombeo.":
        "  ↳ How fast the leveler follows level changes. Fast = follows fast cyclic fading; smooth = more stable, less pumping.",
    "Nivelar en continuo (música / sin detección de voz)":
        "Level continuously (music / no voice detection)",
    "Desactivado (default): el nivelador adapta solo cuando el detector\n"
    "de voz confirma voz presente — evita amplificar el ruido en las\n"
    "pausas entre palabras (ideal para voz en banda ruidosa).\n"
    "Activado: adapta en continuo, sin esperar voz — usar para música o\n"
    "audio continuo, donde no hay estructura de voz que detectar.":
        "Off (default): the leveler adapts only when the voice detector\n"
        "confirms voice is present — avoids amplifying noise in the gaps\n"
        "between words (ideal for voice on noisy bands).\n"
        "On: adapts continuously, without waiting for voice — use for music\n"
        "or continuous audio, where there is no voice structure to detect.",
    "  ↳ Para música o audio continuo con fading: el detector de voz no lo reconoce y el nivelador quedaría congelado — esta casilla lo nivela igual.":
        "  ↳ For music or continuous audio with fading: the voice detector does not recognize it and the leveler would stay frozen — this box levels it anyway.",
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
    "Cascada": "Waterfall",
    "Profundidad de la cascada. Más historia = se ve el QSB y los\n"
    "heterodinos intermitentes a lo largo del tiempo; menos historia =\n"
    "más detalle temporal. No descarta lo ya capturado: es un zoom.":
        "Waterfall depth. More history = QSB and intermittent heterodynes\n"
        "become visible over time; less history = more time detail.\n"
        "It does not discard what was captured: it is a zoom.",
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
    "Ganancia máxima:": "Max gain:",
    "normal": "normal",
    "máximo": "maximum",
    "rápido": "fast",
    "lento": "slow",
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
    "  ↳ Q bajo = boost ancho (más cálido), Q alto = pico angosto (más nasal).":
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
    "  ↳ Saturación tanh: cuántos armónicos se generan y de qué orden. Suave = sutil, agresivo = efecto notable. No cambia el nivel de la banda: solo agrega armónicos nuevos.":
        "  ↳ Tanh saturation: how many harmonics are generated and of what order. Soft = subtle, "
        "aggressive = pronounced. It does not change the band's level: it only adds new harmonics.",
    "Techo de ruido": "Noise ceiling",
    "Limitar la ganancia del AGC según el ruido": "Limit the AGC's gain according to the noise",
    "El AGC lleva la señal a su nivel objetivo sin distinguir voz de ruido:\n"
    "con señal débil sube el ruido de banda hasta +36 dB y queda un siseo\n"
    "molesto. Con esto, su ganancia se topea para que el ruido no pase del\n"
    "nivel elegido. El AGC sigue adaptando (no se congela), así que no puede\n"
    "quedar trabado, y la voz la termina de levantar el Nivelador de voz.":
        "The AGC brings the signal to its target level without telling speech from noise:\n"
        "on a weak signal it lifts the band noise by up to +36 dB and leaves an\n"
        "annoying hiss. With this, its gain is capped so the noise never exceeds the\n"
        "chosen level. The AGC keeps adapting (it is not frozen), so it cannot get\n"
        "stuck, and the Voice leveller finishes lifting the speech.",
    "Tope aplicado:": "Cap applied:",
    "El ruido no pasa de:": "Noise not above:",
    "piso {fl:.0f} dBFS · limitando a +{db:.0f} dB":
        "floor {fl:.0f} dBFS · limiting to +{db:.0f} dB",
    "piso {fl:.0f} dBFS · sin efecto": "floor {fl:.0f} dBFS · no effect",
    "  ↳ Ponerlo POR ENCIMA del piso que muestra el indicador (si queda por debajo, no hay ganancia posible y el tope no sirve). Con señal fuerte el AGC no quiere amplificar y el indicador dice «sin efecto»: es normal, el techo actúa recién cuando la señal se debilita.":
        "  ↳ Set it ABOVE the floor shown by the indicator (below it, no gain is possible and the cap "
        "is useless). On a strong signal the AGC does not want to amplify and the indicator reads «no "
        "effect»: that is normal — the ceiling only acts once the signal weakens.",
    "Mezcla:": "Mix:",
    "Carácter:": "Character:",
    "impar": "odd",
    "mixto": "mixed",
    "par": "even",
    "  ↳ Qué armónicos se generan. Impar (tanh pura) = brillante y algo hueco, es el timbre metálico clásico. Par = más cálido y pleno, pero agrega productos de diferencia en los graves: subirlo mucho puede enturbiar. Mixto suele ser el mejor compromiso.":
        "  ↳ Which harmonics are generated. Odd (pure tanh) = bright and somewhat hollow, the classic "
        "metallic timbre. Even = warmer and fuller, but it adds difference products in the low end: "
        "raising it too far can muddy the sound. Mixed is usually the best compromise.",
    "Recuperar graves:": "Restore bass:",
    "  ↳ Nivel del fundamental recuperado (100% ≈ el que tendría una voz natural). Se deriva de los armónicos de la propia voz: sin voz no hay de dónde derivarlo y se calla solo. Requiere el módulo «Recuperar graves» activo.":
        "  ↳ Level of the recovered fundamental (100% ≈ what a natural voice would have). It is "
        "derived from the voice's own harmonics: with no speech there is nothing to derive it from, "
        "so it goes quiet by itself. Requires the «Restore bass» module enabled.",
    "Recuperar graves": "Restore bass",
    "Devuelve el fundamental de la voz cuando el filtro de la radio ya lo cortó\n"
    "(un pasa-altos de 300 Hz deja un f0 de 120 Hz unos 32 dB abajo: no hay\n"
    "energía que una EQ pueda levantar). Lo DERIVA de los armónicos que sí\n"
    "pasaron, así que suena como parte de la voz y no como un tono agregado.\n"
    "Nivel ajustable en Avanzada Audio.":
        "Brings back the voice's fundamental when the radio's filter has already cut it\n"
        "(a 300 Hz high-pass leaves a 120 Hz f0 some 32 dB down: there is no energy\n"
        "for an EQ to lift). It DERIVES it from the harmonics that did get through, so\n"
        "it sounds like part of the voice and not like an added tone.\n"
        "Level adjustable in Advanced Audio.",
    "  ↳ Nivel de armónicos mezclados. 20–40% = zona útil sin sonar artificial. Con el cancelador activo solo actúa cuando hay voz, así no le agrega brillo al ruido de fondo.":
        "  ↳ Level of harmonics mixed in. 20–40% = useful range without sounding artificial. With the "
        "canceller on it only acts while there is speech, so it doesn't add brightness to the background noise.",

    # --- Avanzada Impulsos ---
    "Supresor de impulsos  (se aplica en tiempo real)": "Impulse suppressor  (applied in real time)",
    "Actividad:": "Activity:",
    "Umbral de trama (10 ms):": "Frame threshold (10 ms):",
    "  ↳ Agresivo = captura más impulsos (QRN fuerte). Suave = solo blancos muy grandes.":
        "  ↳ Aggressive = catches more impulses (heavy QRN). Soft = only very large hits.",
    "Umbral micro (0.67 ms):": "Micro threshold (0.67 ms):",
    "  ↳ Detecta frituras y crackles cortos. Agresivo = elimina más, puede recortar consonantes.":
        "  ↳ Catches short crackle and static. Aggressive = removes more, may clip consonants.",
    "Sensibilidad:": "Sensitivity:",
    "alta": "high",
    "baja": "low",
    "  ↳ Ratio bin/baseline para detectar un tono. Bajar si hay tonos débiles.":
        "  ↳ Bin/baseline ratio to detect a tone. Lower it for weak tones.",
    "Profundidad:": "Depth:",
    "  ↳ Atenuación aplicada al tono detectado. 100%=silencia, 50%=reduce 6dB. Valores altos opacan la voz — 50% suele ser buen balance.":
        "  ↳ Attenuation applied to the detected tone. 100%=silences, 50%=reduces 6 dB. High values muffle the voice — 50% is usually a good balance.",
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
    "estable": "stable",
    "  ↳ Estabiliza la clasificación voz/ruido por bin (menos ruido musical de fondo) y el release del cancelador. Subir si se escucha 'gorgojeo'/pitidos de fondo; 99% deja una cola de ruido tras la voz.":
        "  ↳ Stabilizes the per-bin voice/noise classification (less background musical noise) and the canceller release. Raise it if you hear 'warble'/background birdies; 99% leaves a noise tail after speech.",
    "Velocidad ataque:": "Attack speed:",
    "Reactividad del piso:": "Floor reactivity:",
    "Refuerzo en agudos:": "HF floor boost:",
    "  ↳ Sube el piso de ruido por encima de ~2.5 kHz (donde la energía del ruido es baja y el estimador reacciona tarde). Suprime mejor el siseo de agudos que se cuela con el fading, a costa de algo de brillo de la voz — combinar con Excitador/Presencia para reponerlo.":
        "  ↳ Raises the noise floor above ~2.5 kHz (where noise energy is low and the estimator reacts late). Suppresses the HF hiss that leaks through with fading better, at the cost of some voice brightness — combine with Exciter/Presence to restore it.",
    "  ↳ Ventana de seguimiento del ruido (solo Adaptativo). Reactivo (corto) = el piso sigue subidas rápidas de ruido cíclico, menos vaivén; estable (largo) = mejor con ruido parejo. Con valores reactivos, tener activo el Refuerzo de pitch de voz.":
        "  ↳ Noise tracking window (Adaptive only). Reactive (short) = the floor follows fast rises of cyclic noise, less swaying; stable (long) = better with steady noise. With reactive values, keep Voice pitch reinforcement enabled.",
    "  ↳ Ataque del onset de voz. Rápido = consonantes más nítidas. Suave = transiciones sin artefactos.":
        "  ↳ Voice onset attack. Fast = crisper consonants. Soft = artifact-free transitions.",
    "Compensación fading HF:": "HF fading compensation:",
    "  ↳ Activar en Módulos Activos (sub-módulo del cancelador). Solo modo Adaptativo.":
        "  ↳ Enable in Active Modules (canceller sub-module). Adaptive mode only.",
    "Sensibilidad fading:": "Fading sensitivity:",
    "sensible": "sensitive",
    "selectivo": "selective",
    "  ↳ Cambio de energía que dispara el freeze. Sensible = detecta QSB suave (puede disparar con la voz). Selectivo = solo fades profundos.":
        "  ↳ Energy change that triggers the freeze. Sensitive = detects mild QSB (may trigger on voice). Selective = deep fades only.",
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
    "muy fuerte": "very strong",
    "ancho": "wide",
    "medio": "medium",
    "angosto": "narrow",
    "  ↳ Cuánto se eleva el piso en la zona vocal. 75%=suave, 150%=normal, 250%=fuerte.":
        "  ↳ How much the floor rises in the vocal zone. 75%=soft, 150%=normal, 250%=strong.",
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
    "  ↳ Cuánto baja el piso arriba del 'Inicio' → más supresión del siseo agudo. 55% ≈ −7 dB. En banda angosta (SSB), bajá el 'Inicio' para oírlo.":
        "  ↳ How much the floor drops above 'Start' → more high-hiss suppression. 55% ≈ −7 dB. On narrow bands (SSB), lower 'Start' to hear it.",
    "Post-filtro espectral  (activar en Módulos Activos)":
        "Spectral post-filter  (enable in Active Modules)",
    "Reducción extra:": "Extra reduction:",
    "  ↳ dB extra eliminados en bins de ruido vs cancelador base. 0 dB = sin efecto.":
        "  ↳ Extra dB removed on noise bins vs the base canceller. 0 dB = no effect.",
    "Agresividad:": "Aggressiveness:",
    "desactivado": "off",
    "muy agresivo": "very aggressive",
    "  ↳ Supresión extra en bins de ruido para eliminar 'pitidos fantasma'. 1=normal, 2–3=agresivo, 4+=muy agresivo (vigilar que la voz no se recorte).":
        "  ↳ Extra suppression on noise bins to remove 'ghost birdies'. 1=normal, 2–3=aggressive, 4+=very aggressive (watch for voice clipping).",
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
    "  ↳ Tope de compensación para voz débil. Fuerte = iguala más las señales, pero levanta también el ruido que acompaña a la voz débil.":
        "  ↳ Compensation cap for weak voice. Strong = evens out signals more, but also raises the noise riding along with the weak voice.",

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
    "Dispositivos incompatibles": "Incompatible devices",
    "La entrada ({in_api}) y la salida ({out_api}) usan APIs de audio "
    "distintas y no se pueden combinar en un mismo stream. Elegí ambos "
    "dispositivos de la misma API (por ejemplo, los dos [WASAPI]).":
        "The input ({in_api}) and output ({out_api}) use different audio APIs "
        "and cannot be combined in a single stream. Pick both devices from the "
        "same API (for example, both [WASAPI]).",
    "Dispositivos compatibles. Listo para ACTIVAR.":
        "Compatible devices. Ready to START.",

    # --- Tooltips de los sliders (ui/tooltips.py) ---
    "Cuánto ruido resta el cancelador en los bins que marca como ruido.\n"
    "0% = pasa todo sin tocar; 100% = reducción plena.\n"
    "Calibralo con el Preview: subilo mientras lo que se elimina sea sólo\n"
    "ruido, y bajá un paso donde empiece a filtrarse voz.\n"
    "Receta recomendada: Intensidad baja (50–60%) + Post-Filtro alto.":
        "How much noise the canceller subtracts in the bins it flags as noise.\n"
        "0% = everything passes untouched; 100% = full reduction.\n"
        "Calibrate it with Preview: raise it while what gets removed is only\n"
        "noise, then back off one step where voice starts leaking through.\n"
        "Recommended recipe: low Strength (50-60%) + high Post-Filter.",
    "Nivel máximo al que el AGC puede levantar el ruido de fondo.\n"
    "Ponelo POR ENCIMA del piso que muestra el indicador de al lado: si\n"
    "queda por debajo, no hay ganancia posible y el AGC no amplifica nada.\n"
    "Más bajo = fondo más silencioso cuando la señal es débil o no hay nadie.":
        "Highest level the AGC is allowed to lift background noise to.\n"
        "Set it ABOVE the floor shown by the indicator next to it: if it sits\n"
        "below, no gain is possible and the AGC amplifies nothing.\n"
        "Lower = quieter background when the signal is weak or nobody is on.",
    "Ganancia sobre la señal que llega de la radio, antes de todo el proceso.\n"
    "Ajustala para que el VU de entrada trabaje cómodo sin llegar al rojo:\n"
    "el cancelador y el AGC trabajan mejor con un nivel sano.\n"
    "Si la entrada satura, bajala acá antes que en la radio.":
        "Gain on the signal coming from the radio, before any processing.\n"
        "Set it so the input VU works comfortably without hitting red: the\n"
        "canceller and the AGC do better with a healthy level.\n"
        "If the input clips, turn it down here before touching the radio.",
    "Volumen final que sale al parlante o auricular. También actúa en Bypass.\n"
    "Se recuerda por separado para Bypass encendido y apagado, así podés\n"
    "comparar el antes y el después a nivel parejo.":
        "Final volume sent to the speaker or headphones. It also works in Bypass.\n"
        "It is remembered separately for Bypass on and off, so you can compare\n"
        "before and after at a matched level.",
    "Techo al que el limitador sujeta los picos para que nada sature la salida.\n"
    "−1 a −3 dB es lo habitual. El indicador de al lado avisa cuándo actúa:\n"
    "si está siempre encendido, bajá la ganancia de salida en vez de subir esto.":
        "Ceiling the limiter holds peaks to, so nothing clips the output.\n"
        "-1 to -3 dB is usual. The indicator next to it shows when it acts:\n"
        "if it is always lit, lower the output gain instead of raising this.",
    "Cuántas muestras procesa el DSP por vez. Es el compromiso latencia/CPU:\n"
    "más chico responde antes pero cuesta más; más grande alivia el equipo.\n"
    "480 (10 ms) es el equilibrio; si la CPU va justa, 960 baja bastante el\n"
    "costo y 20 ms de retardo siguen siendo imperceptibles al escuchar.\n"
    "REQUIERE detener y volver a activar el procesamiento.":
        "How many samples the DSP processes at a time. It trades latency for CPU:\n"
        "smaller responds sooner but costs more; larger eases the machine.\n"
        "480 (10 ms) is the balance; if CPU is tight, 960 cuts the cost a lot and\n"
        "20 ms of delay is still imperceptible while listening.\n"
        "REQUIRES stopping and starting processing again.",
    "Cuánto puede amplificar el nivelador a una estación débil para emparejarla\n"
    "con las fuertes. Hacia fuerte = menos manotazos al volumen, pero también\n"
    "levanta el ruido que viene con esa señal débil. 9–12 dB anda bien.":
        "How much the leveler may amplify a weak station to match the strong ones.\n"
        "Toward strong = less reaching for the volume knob, but it also lifts the\n"
        "noise that comes with that weak signal. 9-12 dB works well.",
    "Qué tan rápido persigue el nivelador los cambios de nivel.\n"
    "Rápido (400–600 ms) para fading cíclico y música con QSB; suave (1500 ms\n"
    "o más) para que no bombee. Si escuchás la ganancia 'respirar', andá hacia\n"
    "suave.":
        "How fast the leveler chases level changes.\n"
        "Fast (400-600 ms) for cyclic fading and music with QSB; smooth (1500 ms\n"
        "or more) so it does not pump. If you hear the gain 'breathing', go\n"
        "toward smooth.",
    "Corte inferior del filtro de entrada en AM. Subilo para sacar retumbe,\n"
    "zumbido de red y ruido de motor; bajarlo deja más cuerpo en la voz.":
        "Low cutoff of the input filter in AM. Raise it to remove rumble, mains\n"
        "hum and engine noise; lowering it leaves more body in the voice.",
    "Corte superior del filtro de entrada en AM. Bajarlo saca siseo y QRM del\n"
    "canal de al lado; subirlo deja más brillo y claridad en las consonantes.":
        "High cutoff of the input filter in AM. Lowering it removes hiss and QRM\n"
        "from the adjacent channel; raising it leaves more brightness and clearer\n"
        "consonants.",
    "Corte inferior del filtro de entrada en SSB. En banda angosta subirlo un\n"
    "poco (300 Hz) limpia mucho retumbe sin tocar la inteligibilidad.":
        "Low cutoff of the input filter in SSB. In narrow band, raising it a bit\n"
        "(300 Hz) cleans up a lot of rumble without hurting intelligibility.",
    "Corte superior del filtro de entrada en SSB. 2700–2900 Hz es el ancho\n"
    "clásico de fonía; angostarlo le da menos soplido que masticar al cancelador.":
        "High cutoff of the input filter in SSB. 2700-2900 Hz is the classic voice\n"
        "width; narrowing it gives the canceller less hiss to chew on.",
    "Corte inferior del filtro de SALIDA en AM (sólo con 'Salida independiente').\n"
    "Sirve para dejar la entrada angosta —menos ruido al cancelador— y la salida\n"
    "más ancha, para que la voz no llegue doblemente apagada.":
        "Low cutoff of the OUTPUT filter in AM (only with 'Output independent').\n"
        "Useful to keep the input narrow -less noise into the canceller- and the\n"
        "output wider, so the voice does not arrive doubly muffled.",
    "Corte superior del filtro de SALIDA en AM (sólo con 'Salida independiente').\n"
    "Poniéndolo por encima del corte de entrada se recupera el borde de la voz\n"
    "que se perdía al encadenar dos filtros con el mismo corte.":
        "High cutoff of the OUTPUT filter in AM (only with 'Output independent').\n"
        "Setting it above the input cutoff recovers the edge of the voice that was\n"
        "lost when chaining two filters with the same cutoff.",
    "Corte inferior del filtro de SALIDA en SSB (sólo con 'Salida independiente').":
        "Low cutoff of the OUTPUT filter in SSB (only with 'Output independent').",
    "Corte superior del filtro de SALIDA en SSB (sólo con 'Salida independiente').\n"
    "3200–3500 Hz con la entrada en 2700 deja la voz más abierta sin dejar\n"
    "entrar más ruido al cancelador.":
        "High cutoff of the OUTPUT filter in SSB (only with 'Output independent').\n"
        "3200-3500 Hz with the input at 2700 leaves the voice more open without\n"
        "letting more noise into the canceller.",
    "Qué tan abrupto es el corte en el borde de la banda.\n"
    "Mayor orden = paredes más verticales contra el QRM vecino, pero más\n"
    "ringing en los transitorios y más CPU. 4 es el default sensato; 6–8 sólo\n"
    "si te entra una estación pegada al costado.":
        "How steep the cutoff is at the band edge.\n"
        "Higher order = more vertical walls against adjacent QRM, but more ringing\n"
        "on transients and more CPU. 4 is the sensible default; 6-8 only if a\n"
        "station is sitting right next to you.",
    "Dónde se aplica el refuerzo de cuerpo. Buscá el fundamental del corresponsal:\n"
    "300–400 Hz en voces graves, 400–500 Hz en agudas.\n"
    "Movelo mientras escuchás hasta que la voz gane 'pecho'.":
        "Where the body boost is applied. Look for the correspondent's fundamental:\n"
        "300-400 Hz on deep voices, 400-500 Hz on higher ones.\n"
        "Move it while listening until the voice gains 'chest'.",
    "Cuánto se refuerza esa banda. +2 a +4 dB alcanza para dar cuerpo; más\n"
    "empieza a retumbar y tapa la claridad. En 0 dB no hace nada.":
        "How much that band is boosted. +2 to +4 dB is enough for body; more starts\n"
        "to boom and masks clarity. At 0 dB it does nothing.",
    "Dónde se aplica el realce de presencia. 1500–2000 Hz es la zona de las\n"
    "consonantes, que es lo que hace entender las palabras.\n"
    "Más abajo suena nasal, más arriba sisea.":
        "Where the presence boost is applied. 1500-2000 Hz is the consonant range,\n"
        "which is what makes words understandable.\n"
        "Lower sounds nasal, higher hisses.",
    "Cuánto se realza la presencia. +3 a +6 dB despabila una voz apagada.\n"
    "Ojo: también levanta el siseo que dejó el cancelador. En 0 dB no hace nada.":
        "How much presence is boosted. +3 to +6 dB wakes up a dull voice.\n"
        "Careful: it also lifts the hiss the canceller left. At 0 dB it does nothing.",
    "Ancho de la campana de presencia. Angosto corrige un punto muy concreto;\n"
    "ancho suena más natural pero mueve más banda.\n"
    "Empezá ancho y angostá sólo si buscás algo puntual.":
        "Width of the presence bell. Narrow fixes one very specific spot; wide\n"
        "sounds more natural but moves more of the band.\n"
        "Start wide and narrow it only if you are after something specific.",
    "Corrige el tono cuando el BFO de la radio está corrido y las voces suenan\n"
    "de pato o de ultratumba. Movelo hasta que suene natural.\n"
    "En 0 Hz no hace nada; en AM dejalo en 0.":
        "Corrects pitch when the radio's BFO is off and voices sound like a duck or\n"
        "come from beyond the grave. Move it until it sounds natural.\n"
        "At 0 Hz it does nothing; in AM leave it at 0.",
    "Cuánta saturación se usa para fabricar los armónicos que la radio perdió.\n"
    "Suave (1–3) es sutil; agresivo (6–10) genera armónicos de orden más alto y\n"
    "puede sonar duro. No cambia el volumen ni depende del nivel de la señal.":
        "How much saturation is used to build the harmonics the radio lost.\n"
        "Soft (1-3) is subtle; aggressive (6-10) generates higher-order harmonics\n"
        "and can sound harsh. It changes neither volume nor depends on signal level.",
    "Cuánto de esos armónicos se suma al audio. 20–40% es la zona útil;\n"
    "por encima de 60% empieza a sonar artificial.\n"
    "Con el cancelador activo sólo actúa cuando hay voz.":
        "How much of those harmonics is added to the audio. 20-40% is the useful\n"
        "range; above 60% it starts to sound artificial.\n"
        "With the canceller active it only acts when there is voice.",
    "Timbre de los armónicos generados, no volumen.\n"
    "Impar = brillante y algo hueco (el clásico sonido metálico); par = más\n"
    "cálido y pleno, pero mete productos de diferencia en los graves.\n"
    "Mixto (30–60%) suele ser el mejor compromiso.":
        "Timbre of the generated harmonics, not volume.\n"
        "Odd = bright and slightly hollow (the classic metallic sound); even =\n"
        "warmer and fuller, but it adds difference products in the bass.\n"
        "Mixed (30-60%) is usually the best compromise.",
    "Nivel del fundamental grave que la radio no transmitió y se reconstruye\n"
    "a partir de los armónicos que sí llegaron. 100% ≈ el que tendría una voz\n"
    "natural. Empezá en 35% y subí de a poco: el exceso de graves se nota\n"
    "enseguida. Se calla solo cuando no hay voz.":
        "Level of the low fundamental the radio never transmitted, rebuilt from the\n"
        "harmonics that did arrive. 100% is roughly what a natural voice would have.\n"
        "Start at 35% and go up slowly: too much bass shows up quickly.\n"
        "It goes quiet on its own when there is no voice.",
    "Cuántas veces por encima del piso de ruido tiene que estar un pico de\n"
    "10 ms para borrarlo (chasquidos de encendido, arranques de motor).\n"
    "Agresivo puede comerse consonantes fuertes; suave deja pasar impulsos.\n"
    "15 es un buen punto de partida.":
        "How many times above the noise floor a 10 ms peak has to be for it to be\n"
        "erased (switch clicks, engine starts).\n"
        "Aggressive may eat strong consonants; soft lets impulses through.\n"
        "15 is a good starting point.",
    "Lo mismo pero para micro-impulsos de menos de 1 ms: cerco eléctrico,\n"
    "línea de alta tensión, chispas.\n"
    "Bajalo si escuchás 'tics' rápidos que el otro umbral no agarra.":
        "Same thing but for micro-impulses under 1 ms: electric fences, power lines,\n"
        "sparks.\n"
        "Lower it if you hear fast 'ticks' the other threshold does not catch.",
    "Cuánto tiene que sobresalir una frecuencia sobre sus vecinas para que el\n"
    "ANF la trate como tono. Sensibilidad alta agarra heterodinos débiles pero\n"
    "puede tocar armónicos de la voz; baja va sólo por los silbidos evidentes.":
        "How far a frequency has to stand above its neighbours for the ANF to treat\n"
        "it as a tone. High sensitivity catches weak heterodynes but may touch voice\n"
        "harmonics; low goes only after the obvious whistles.",
    "Cuánto se atenúa el tono detectado.\n"
    "OJO: valores altos opacan bastante la voz — 50% es el balance recomendado.\n"
    "Si el heterodino sigue molestando, probá primero subir la Sensibilidad.":
        "How much the detected tone is attenuated.\n"
        "CAREFUL: high values noticeably dull the voice - 50% is the recommended\n"
        "balance. If the heterodyne still bothers you, try raising Sensitivity first.",
    "Ganancia mínima que puede tomar un bin: cuánto ruido se deja pasar en los\n"
    "que el detector marca como ruido. 0.10 = nunca se le quita más del 90 %\n"
    "de la energía. Más bajo = más silencio, pero más riesgo de gorgojeo y de\n"
    "que suene 'muerto'. 0.10–0.15 es lo habitual; no bajar de 0.05.\n"
    "Un piso alto también transmite más el swing del fading.":
        "Minimum gain a bin can take: how much noise is let through in the ones\n"
        "the detector flags as noise. 0.10 = no bin ever loses more than 90 % of\n"
        "its energy. Lower = more silence, but more risk of warbling and of\n"
        "sounding 'dead'. 0.10-0.15 is usual; do not go below 0.05.\n"
        "A high floor also passes more of the fading swing.",
    "Estabiliza la clasificación voz/ruido entre frames, que es de donde sale\n"
    "el ruido musical. Hacia suave = fondo más parejo y sin gorgojeo; hacia\n"
    "reactivo el cancelador responde antes. La zona útil es 96–98%.":
        "Stabilises the voice/noise decision between frames, which is where musical\n"
        "noise comes from. Toward smooth = flatter background with no warbling;\n"
        "toward reactive the canceller responds sooner. Useful range: 96-98%.",
    "Qué tan rápido sube la ganancia en los bins donde aparece voz.\n"
    "Rápido conserva mejor el ataque de cada palabra; suave reduce artefactos.\n"
    "Si la voz suena recortada al arrancar, hacelo más rápido.":
        "How fast gain rises in the bins where voice appears.\n"
        "Fast preserves the attack of each word better; smooth reduces artifacts.\n"
        "If the voice sounds clipped at the start, make it faster.",
    "Cada cuánto puede reaccionar el estimador a cambios del ruido (sólo en\n"
    "modo Adaptativo). Corto sigue el ruido cíclico típico de onda corta;\n"
    "largo da un estimado más estable.\n"
    "Si el ruido cambia rápido y sentís un vaivén, acortalo.":
        "How often the estimator may react to noise changes (Adaptive mode only).\n"
        "Short follows the cyclic noise typical of shortwave; long gives a more\n"
        "stable estimate.\n"
        "If the noise changes fast and you feel a see-saw, shorten it.",
    "Sube el piso estimado por encima de ~2.5 kHz, donde el estimador queda\n"
    "corto y se cuela el siseo. Es progresivo: cuanto más alta la frecuencia,\n"
    "más refuerzo. Cuesta algo de brillo — compensá con Excitador o Presencia.":
        "Raises the estimated floor above ~2.5 kHz, where the estimator falls short\n"
        "and hiss leaks through. It is progressive: the higher the frequency, the\n"
        "more boost. It costs some brightness - make up for it with the Exciter or\n"
        "Presence.",
    "Cuánto tiene que cambiar la energía para dar un desvanecimiento por\n"
    "detectado. Sensible (1–4 dB) dispara con QSB suave; selectivo sólo con\n"
    "fades marcados. Sólo cuenta si además hay voz presente, así que una\n"
    "subida de ruido de banda no lo dispara.":
        "How much the energy has to change before a fade counts as detected.\n"
        "Sensitive (1-4 dB) triggers on gentle QSB; selective only on marked fades.\n"
        "It only counts if there is voice present too, so a broadband noise rise\n"
        "does not trigger it.",
    "Cuánto tiempo queda congelado el estimador de ruido después de detectar\n"
    "un desvanecimiento, para que no aprenda el bajón como si fuera el piso.\n"
    "Más largo protege mejor en fades lentos; más corto vuelve antes a seguir\n"
    "el ruido real.":
        "How long the noise estimator stays frozen after detecting a fade, so it\n"
        "does not learn the dip as if it were the floor.\n"
        "Longer protects better on slow fades; shorter goes back to tracking the\n"
        "real noise sooner.",
    "Cuánta certeza de que hay voz hace falta para abrir el gate y dejar pasar\n"
    "el audio. Sensible abre fácil (y deja pasar ruido); selectivo filtra mejor\n"
    "pero puede cortar voz débil. Si el gate no abre con señales flojas,\n"
    "hacelo más sensible.":
        "How much certainty that there is voice is needed to open the gate and let\n"
        "audio through. Sensitive opens easily (and lets noise in); selective filters\n"
        "better but may cut weak voice. If the gate will not open on weak signals,\n"
        "make it more sensitive.",
    "Cuánto se mantiene abierto el gate después de que se dejó de detectar voz.\n"
    "Corto corta las pausas entre palabras; largo deja pasar más ruido entre\n"
    "frases. 300–500 ms es lo habitual.":
        "How long the gate stays open after voice stops being detected.\n"
        "Short cuts the pauses between words; long lets more noise through between\n"
        "sentences. 300-500 ms is usual.",
    "Cuánto se levanta el piso en la zona de los fundamentales de la voz, para\n"
    "que el cancelador no se lleve la calidez. Hacia fuerte = voz más llena, a\n"
    "costa de dejar pasar algo más de ruido en esa banda.":
        "How much the floor is raised in the range of the voice fundamentals, so the\n"
        "canceller does not take the warmth away. Toward strong = fuller voice, at\n"
        "the cost of letting slightly more noise through in that band.",
    "Dónde se centra ese refuerzo. Bajalo para voces graves y subilo para\n"
    "agudas, siguiendo el fundamental del corresponsal.":
        "Where that boost is centred. Lower it for deep voices and raise it for\n"
        "higher ones, following the correspondent's fundamental.",
    "Desde qué frecuencia el piso empieza a bajar, o sea desde dónde se suprime\n"
    "más en agudos. En banda angosta bajalo: si arranca después del borde de la\n"
    "banda, el módulo no llega a actuar.":
        "From which frequency the floor starts to drop, that is, from where highs get\n"
        "suppressed more. In narrow band, lower it: if it starts past the band edge,\n"
        "the module never gets to act.",
    "Cuánto llega a bajar el piso en los agudos. Más profundo = menos siseo\n"
    "pero también menos brillo. En SSB angosto el efecto siempre va a ser menor\n"
    "que en AM, por el ancho de banda disponible.":
        "How far the floor drops in the highs. Deeper = less hiss but also less\n"
        "brightness. In narrow SSB the effect will always be smaller than in AM,\n"
        "because of the available bandwidth.",
    "Cuánto se protegen del cancelador los armónicos de la voz detectada.\n"
    "Fuerte rescata mejor una voz enterrada en ruido; si el tono se detecta mal,\n"
    "puede terminar protegiendo bins que eran ruido.":
        "How much the harmonics of the detected voice are protected from the\n"
        "canceller. Strong rescues a voice buried in noise better; if pitch detection\n"
        "goes wrong, it may end up protecting bins that were noise.",

    # --- Escala de la interfaz ---
    "Tamaño de la interfaz: agranda todos los textos y controles a la vez\n"
    "(útil en monitores donde la letra queda chica). No cambia el audio ni\n"
    "el procesamiento. Requiere reiniciar la aplicación.":
        "Interface size: enlarges every text and control at once (useful on\n"
        "monitors where the type is too small). It changes neither the audio nor\n"
        "the processing. Requires restarting the application.",
    "Tamaño de la interfaz guardado ({pct} %) — reiniciar la aplicación para aplicarlo.":
        "Interface size saved ({pct} %) — restart the application to apply it.",
    "La escala de la interfaz no entra en esta pantalla — se volvio a 100 %. Reiniciar la aplicacion.":
        "The interface scale does not fit this screen — reset to 100 %. Restart the application.",
}

"""
ui.tooltips — textos de ayuda de los sliders (tooltip al pasar el mouse).

Viven en una tabla aparte indexada por el NOMBRE DEL ATRIBUTO del SliderRow,
en vez de repartidos por cada llamada al constructor: las pestañas de Avanzadas
ya son archivos largos, y así el texto de ayuda se lee, se revisa y se traduce
todo junto.

`apply_tooltips()` recorre los atributos del widget y aplica lo que encuentre;
un slider sin entrada simplemente queda sin tooltip. La red de seguridad es
`tests/test_ui.py::test_all_sliders_have_tooltip`, que exige que TODO SliderRow
de la app tenga uno — al agregar un slider nuevo hay que agregar su entrada acá
(y su clave en i18n_en.py).

Estilo de los textos: qué hace el control en criollo, hacia dónde moverlo y qué
se paga a cambio. Nada de repetir el nombre del slider.
"""
from i18n import tr
from ui.slider_row import SliderRow


SLIDER_TIPS = {
    # ---------------- Principal ---------------- #
    "_slider_noise": (
        "Cuánto ruido resta el cancelador en los bins que marca como ruido.\n"
        "0% = pasa todo sin tocar; 100% = reducción plena.\n"
        "Calibralo con el Preview: subilo mientras lo que se elimina sea sólo\n"
        "ruido, y bajá un paso donde empiece a filtrarse voz.\n"
        "Receta recomendada: Intensidad baja (50–60%) + Post-Filtro alto."
    ),
    "_s_agc_ceiling": (
        "Nivel máximo al que el AGC puede levantar el ruido de fondo.\n"
        "Ponelo POR ENCIMA del piso que muestra el indicador de al lado: si\n"
        "queda por debajo, no hay ganancia posible y el AGC no amplifica nada.\n"
        "Más bajo = fondo más silencioso cuando la señal es débil o no hay nadie.\n"
        "Es un ajuste de TU estación: el piso depende del QTH, la antena y la\n"
        "banda, así que no hay un valor recomendado. Calibralo escuchando."
    ),
    "_s_gain_in": (
        "Ganancia sobre la señal que llega de la radio, antes de todo el proceso.\n"
        "Ajustala para que el VU de entrada trabaje cómodo sin llegar al rojo:\n"
        "el cancelador y el AGC trabajan mejor con un nivel sano.\n"
        "Si la entrada satura, bajala acá antes que en la radio."
    ),
    "_s_gain_out": (
        "Volumen final que sale al parlante o auricular. También actúa en Bypass.\n"
        "Se recuerda por separado para Bypass encendido y apagado, así podés\n"
        "comparar el antes y el después a nivel parejo."
    ),
    "_s_peak": (
        "Techo al que el limitador sujeta los picos para que nada sature la salida.\n"
        "−1 a −3 dB es lo habitual. El indicador de al lado avisa cuándo actúa:\n"
        "si está siempre encendido, bajá la ganancia de salida en vez de subir esto."
    ),

    # ---------------- Avanzada Audio ---------------- #
    "_s_block": (
        "Cuántas muestras procesa el DSP por vez. Es el compromiso latencia/CPU:\n"
        "más chico responde antes pero cuesta más; más grande alivia el equipo.\n"
        "480 (10 ms) es el equilibrio; si la CPU va justa, 960 baja bastante el\n"
        "costo y 20 ms de retardo siguen siendo imperceptibles al escuchar.\n"
        "REQUIERE detener y volver a activar el procesamiento."
    ),
    "_s_leveler_max": (
        "Cuánto puede amplificar el nivelador a una estación débil para emparejarla\n"
        "con las fuertes. Hacia fuerte = menos manotazos al volumen, pero también\n"
        "levanta el ruido que viene con esa señal débil. 9–12 dB anda bien."
    ),
    "_s_leveler_release": (
        "Qué tan rápido persigue el nivelador los cambios de nivel.\n"
        "Rápido (400–600 ms) para fading cíclico y música con QSB; suave (1500 ms\n"
        "o más) para que no bombee. Si escuchás la ganancia 'respirar', andá hacia\n"
        "suave."
    ),
    "_s_am_lo": (
        "Corte inferior del filtro de entrada en AM. Subilo para sacar retumbe,\n"
        "zumbido de red y ruido de motor; bajarlo deja más cuerpo en la voz."
    ),
    "_s_am_hi": (
        "Corte superior del filtro de entrada en AM. Bajarlo saca siseo y QRM del\n"
        "canal de al lado; subirlo deja más brillo y claridad en las consonantes."
    ),
    "_s_ssb_lo": (
        "Corte inferior del filtro de entrada en SSB. En banda angosta subirlo un\n"
        "poco (300 Hz) limpia mucho retumbe sin tocar la inteligibilidad."
    ),
    "_s_ssb_hi": (
        "Corte superior del filtro de entrada en SSB. 2700–2900 Hz es el ancho\n"
        "clásico de fonía; angostarlo le da menos soplido que masticar al cancelador."
    ),
    "_s_out_am_lo": (
        "Corte inferior del filtro de SALIDA en AM (sólo con 'Salida independiente').\n"
        "Sirve para dejar la entrada angosta —menos ruido al cancelador— y la salida\n"
        "más ancha, para que la voz no llegue doblemente apagada."
    ),
    "_s_out_am_hi": (
        "Corte superior del filtro de SALIDA en AM (sólo con 'Salida independiente').\n"
        "Poniéndolo por encima del corte de entrada se recupera el borde de la voz\n"
        "que se perdía al encadenar dos filtros con el mismo corte."
    ),
    "_s_out_ssb_lo": (
        "Corte inferior del filtro de SALIDA en SSB (sólo con 'Salida independiente')."
    ),
    "_s_out_ssb_hi": (
        "Corte superior del filtro de SALIDA en SSB (sólo con 'Salida independiente').\n"
        "3200–3500 Hz con la entrada en 2700 deja la voz más abierta sin dejar\n"
        "entrar más ruido al cancelador."
    ),
    "_s_order": (
        "Qué tan abrupto es el corte en el borde de la banda.\n"
        "Mayor orden = paredes más verticales contra el QRM vecino, pero más\n"
        "ringing en los transitorios y más CPU. 4 es el default sensato; 6–8 sólo\n"
        "si te entra una estación pegada al costado."
    ),
    "_s_body_freq": (
        "Dónde se aplica el refuerzo de cuerpo. Buscá el fundamental del corresponsal:\n"
        "300–400 Hz en voces graves, 400–500 Hz en agudas.\n"
        "Movelo mientras escuchás hasta que la voz gane 'pecho'."
    ),
    "_s_body": (
        "Cuánto se refuerza esa banda. +2 a +4 dB alcanza para dar cuerpo; más\n"
        "empieza a retumbar y tapa la claridad. En 0 dB no hace nada."
    ),
    "_s_presence_freq": (
        "Dónde se aplica el realce de presencia. 1500–2000 Hz es la zona de las\n"
        "consonantes, que es lo que hace entender las palabras.\n"
        "Más abajo suena nasal, más arriba sisea.\n"
        "Por encima de 2500 Hz sólo sirve en AM, donde el pasabanda llega a\n"
        "4–5 kHz: en SSB la banda termina antes y el filtro se come el realce."
    ),
    "_s_presence": (
        "Cuánto se realza la presencia. +3 a +6 dB despabila una voz apagada.\n"
        "Ojo: también levanta el siseo que dejó el cancelador. En 0 dB no hace nada."
    ),
    "_s_presence_q": (
        "Ancho de la campana de presencia. Angosto corrige un punto muy concreto;\n"
        "ancho suena más natural pero mueve más banda.\n"
        "Empezá ancho y angostá sólo si buscás algo puntual."
    ),
    "_s_exciter_drive": (
        "Cuánta saturación se usa para fabricar los armónicos que la radio perdió.\n"
        "Suave (1–3) es sutil; agresivo (6–10) genera armónicos de orden más alto y\n"
        "puede sonar duro. No cambia el volumen ni depende del nivel de la señal."
    ),
    "_s_exciter_mix": (
        "Cuánto de esos armónicos se suma al audio. 20–40% es la zona útil;\n"
        "por encima de 60% empieza a sonar artificial.\n"
        "Con el cancelador activo sólo actúa cuando hay voz."
    ),
    "_s_exciter_char": (
        "Timbre de los armónicos generados, no volumen.\n"
        "Impar = brillante y algo hueco (el clásico sonido metálico); par = más\n"
        "cálido y pleno, pero mete productos de diferencia en los graves.\n"
        "Mixto (30–60%) suele ser el mejor compromiso."
    ),
    "_s_bass": (
        "Nivel del fundamental grave que la radio no transmitió y se reconstruye\n"
        "a partir de los armónicos que sí llegaron. 100% ≈ el que tendría una voz\n"
        "natural. Empezá en 35% y subí de a poco: el exceso de graves se nota\n"
        "enseguida. Se calla solo cuando no hay voz."
    ),

    # ---------------- Avanzada Impulsos ---------------- #
    "_s_blanker_frame": (
        "Cuántas veces por encima de SUS VECINOS inmediatos tiene que estar un\n"
        "pico de 10 ms para borrarlo (chasquidos, arranques de motor). Compara\n"
        "contra el nivel de al lado, no contra el piso: la voz es sostenida, así\n"
        "que sus vecinos están igual de fuertes y no dispara.\n"
        "Agresivo puede comerse consonantes fuertes; suave deja pasar impulsos.\n"
        "15 es un buen punto de partida."
    ),
    "_s_blanker_mini": (
        "Lo mismo pero para micro-impulsos de menos de 1 ms: cerco eléctrico,\n"
        "línea de alta tensión, chispas.\n"
        "Bajalo si escuchás 'tics' rápidos que el otro umbral no agarra, o si\n"
        "con QRN de descargas te parece que suprime de menos."
    ),
    "_s_anf_threshold": (
        "Cuánto tiene que sobresalir una frecuencia sobre sus vecinas para que el\n"
        "ANF la trate como tono. Sensibilidad alta agarra heterodinos débiles pero\n"
        "puede tocar armónicos de la voz; baja va sólo por los silbidos evidentes."
    ),
    "_s_anf_depth": (
        "Cuánto se atenúa el tono detectado. 100% lo silencia del todo.\n"
        "Se puede subir sin miedo: el ANF solo actúa sobre tonos que se\n"
        "sostienen, así que ya no confunde armónicos de la voz con heterodinos.\n"
        "Si el tono igual persiste, probá subir también la Sensibilidad."
    ),

    # ---------------- Avanzada Cancelador ---------------- #
    "_s_noise_floor": (
        "Ganancia mínima que puede tomar un bin: cuánto ruido se deja pasar en los\n"
        "que el detector marca como ruido. 0.10 = nunca se le quita más del 90 %\n"
        "de la energía. Más bajo = más silencio, pero más riesgo de gorgojeo y de\n"
        "que suene 'muerto'. 0.12–0.20 es la zona útil; no bajar de 0.05.\n"
        "Con QSB, SUBIRLO reduce cuánto se nota el fading: el cancelador deja\n"
        "de variar tanto su ganancia con la señal (medido: de 0.10 a 0.20, el\n"
        "vaivén de nivel baja 4 dB). Se paga con menos supresión de ruido."
    ),
    "_s_noise_smooth": (
        "Estabiliza la clasificación voz/ruido entre frames, que es de donde sale\n"
        "el ruido musical. Hacia suave = fondo más parejo y sin gorgojeo; hacia\n"
        "reactivo el cancelador responde antes. La zona útil es 96–98%."
    ),
    "_s_noise_attack": (
        "Qué tan rápido sube la ganancia en los bins donde aparece voz.\n"
        "Rápido conserva mejor el ataque de cada palabra; suave reduce artefactos.\n"
        "Si la voz suena recortada al arrancar, hacelo más rápido."
    ),
    "_s_noise_fall": (
        "Cuán rápido puede BAJAR el piso de ruido estimado. Subir es siempre libre.\n"
        "Cuando el ruido de banda sube de golpe, la salida salta porque el piso llegó\n"
        "tarde; si el piso no se hundió en los ratos flojos, tiene menos que recuperar.\n"
        "Fuerte deja el fondo más parejo pero cuesta un poco de voz, y tarda más en\n"
        "aprovechar una banda que se limpió de verdad. Sin freno = como hasta la v2.2.\n"
        "Solo tiene efecto en modo Adaptativo."
    ),
    "_s_mcra_window": (
        "Cada cuánto puede reaccionar el estimador a cambios del ruido (sólo en\n"
        "modo Adaptativo). Corto sigue el ruido cíclico típico de onda corta;\n"
        "largo da un estimado más estable.\n"
        "Si el ruido cambia rápido y sentís un vaivén, acortalo."
    ),
    "_s_hf_boost": (
        "Sube el piso estimado por encima de ~2.5 kHz, donde el estimador queda\n"
        "corto y se cuela el siseo. Es progresivo: cuanto más alta la frecuencia,\n"
        "más refuerzo. Cuesta algo de brillo — compensá con Excitador o Presencia."
    ),
    "_s_squelch_threshold": (
        "Cuánta certeza de que hay voz hace falta para abrir el gate y dejar pasar\n"
        "el audio. Sensible abre fácil (y deja pasar ruido); selectivo filtra mejor\n"
        "pero puede cortar voz débil. Si el gate no abre con señales flojas,\n"
        "hacelo más sensible."
    ),
    "_s_squelch_hold": (
        "Cuánto se mantiene abierto el gate después de que se dejó de detectar voz.\n"
        "Corto corta las pausas entre palabras; largo deja pasar más ruido entre\n"
        "frases. 300–500 ms es lo habitual."
    ),
    "_s_pf_boost": (
        "Cuánto se levanta el piso en la zona de los fundamentales de la voz, para\n"
        "que el cancelador no se lleve la calidez. Hacia fuerte = voz más llena, a\n"
        "costa de dejar pasar algo más de ruido en esa banda."
    ),
    "_s_pf_center": (
        "Dónde se centra ese refuerzo. Bajalo para voces graves y subilo para\n"
        "agudas, siguiendo el fundamental del corresponsal."
    ),
    "_s_pf_rolloff_hz": (
        "Desde qué frecuencia el piso empieza a bajar, o sea desde dónde se suprime\n"
        "más en agudos. En banda angosta bajalo: si arranca después del borde de la\n"
        "banda, el módulo no llega a actuar."
    ),
    "_s_pf_rolloff_depth": (
        "Cuánto llega a bajar el piso en los agudos. Más profundo = menos siseo\n"
        "pero también menos brillo. En SSB angosto el efecto siempre va a ser menor\n"
        "que en AM, por el ancho de banda disponible."
    ),
    "_s_pitch_strength": (
        "Cuánto se protegen del cancelador los armónicos de la voz detectada.\n"
        "Fuerte rescata mejor una voz enterrada en ruido; si el tono se detecta mal,\n"
        "puede terminar protegiendo bins que eran ruido.\n"
        "Necesita resolución para separar armónicos: con bloque 240–480 y voz grave\n"
        "no discrimina y sale caro en supresión. Para este módulo, bloque 960 o 1920."
    ),
}


def apply_tooltips(widget) -> None:
    """Aplica el tooltip que corresponda a cada SliderRow del widget.

    Se llama DESPUÉS de construir la UI. Los atributos sin entrada en la tabla
    se saltean (los que ya traen tooltip propio desde el constructor no se pisan)."""
    for name, obj in vars(widget).items():
        if isinstance(obj, SliderRow) and not obj.toolTip():
            text = SLIDER_TIPS.get(name)
            if text:
                obj.setToolTip(tr(text))

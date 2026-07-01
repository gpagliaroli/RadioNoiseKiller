# Reductor de Ruido Radio — Manual de Usuario

---

## Introducción

**Reductor de Ruido Radio** es una aplicación para Windows que procesa en tiempo real el audio de una radio AM/SSB antes de que llegue a los parlantes o auriculares. Se ubica entre la salida de audio de la radio (o receptor SDR) y la reproducción final, actuando como una cadena de filtros digitales diseñados específicamente para el tipo de ruido que aparece en las bandas de onda corta y AM.

### ¿Para qué sirve?

En radioafición y escucha de onda corta, el audio suele estar degradado por:

- **Ruido de banda** (estático, ruido blanco de fondo)
- **Impulsos atmosféricos** (QRN, descargas eléctricas, frituras)
- **Interferencias de tonos** (heterodinos, portadoras AM de otras estaciones, armónicos de red)
- **Ancho de banda excesivo** (frecuencias fuera de la voz que agregan ruido innecesario)

La aplicación aplica una serie de procesos en cadena — el **pipeline** — donde cada etapa ataca un tipo de degradación específico. El resultado es audio más limpio, con mayor inteligibilidad de voz, sin introducir artefactos artificiales audibles.

### ¿Cómo se usa en la práctica?

1. Conectar la salida de audio de la radio a una entrada de la PC (línea in, o virtual cable si es SDR por software).
2. Seleccionar esa entrada como **dispositivo de entrada** en la aplicación.
3. Seleccionar los parlantes o auriculares como **dispositivo de salida**.
4. Configurar el modo (AM o SSB) y pulsar **ACTIVAR**.
5. Ajustar los módulos según el tipo de señal y condiciones de propagación.

### Lo que la aplicación NO hace

- No demodula la señal de RF — recibe audio ya demodulado.
- No corrige desvanecimientos (fading) de propagación.
- No mejora señales con nivel de señal (S-meter) muy bajo — necesita algo de señal para trabajar.

---

## Diagrama del Pipeline

El audio recorre los siguientes procesos en orden. Cada etapa puede activarse o desactivarse de forma independiente:

```
┌─────────────────────────────────────────────────────────────┐
│                       AUDIO ENTRADA                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    [ Ganancia de entrada ]
                           │
             [ Supresor de Impulsos (pre-AGC) ]
               Elimina QRN y descargas breves
                           │
                        [ AGC ]
               Control automático de ganancia
                           │
            [ Filtro de Paso de Banda  ── PRE ]
          Limita el espectro antes del cancelador
                           │
          [ ANF — Filtro de Muesca Espectral ]
            Cancela heterodinos y tonos fijos
                           │
         [ Cancelador de Ruido Estacionario ]
           Filtro Wiener espectral adaptativo
                           │
               [ Squelch de Voz  (opcional) ]
          Silencia la salida entre transmisiones
                           │
            [ Filtro de Paso de Banda  ── POST ]
         Limpia fugas espectrales post-procesado
                           │
                   [ EQ de Presencia ]
            Realce de consonantes y legibilidad
                           │
              [ Excitador Armónico  (opcional) ]
           Genera armónicos para recuperar brillo
                           │
                  [ Ganancia de salida ]
                  Limitador de picos
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                       AUDIO SALIDA                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Capítulo 1 — Dispositivos de Audio

**Ubicación:** Pestaña Principal → grupo "Dispositivos de Audio"

### Descripción

Selecciona de dónde viene el audio (entrada) y a dónde va (salida). La aplicación solo muestra dispositivos **WASAPI** y **WDM-KS**, que son los drivers de Windows con menor latencia.

### Controles

| Control | Descripción |
|---------|-------------|
| **Entrada** | Fuente de audio. Puede ser una entrada física (línea in, micrófono), una tarjeta de audio virtual (VB-Cable, etc.) o "Mezcla estéreo" para capturar lo que reproduce otra aplicación. |
| **Salida** | Destino del audio procesado. Típicamente los parlantes o auriculares. |

### Consejos

- Si usás un SDR por software (HDSDR, SDR#, etc.), configurá en ese programa la salida hacia un **cable de audio virtual** y seleccioná ese cable como entrada aquí.
- Si la lista aparece vacía o incompleta, reiniciar la aplicación suele resolver problemas de enumeración de dispositivos Windows.
- El cambio de dispositivo requiere detener y volver a activar el procesamiento.

---

## Capítulo 2 — Control General

**Ubicación:** Pestaña Principal → grupo "Control"

### Descripción

Controles principales de operación: modo de recepción, AGC y activación del procesamiento.

### Controles

| Control | Descripción |
|---------|-------------|
| **Modo** | Selecciona el tipo de señal recibida: **AM** (amplitud modulada, ancho de banda más amplio) o **SSB** (banda lateral única, voz comprimida en frecuencia). Afecta los límites por defecto del Filtro de Paso de Banda. |
| **AGC** | Control Automático de Ganancia. **off** = sin AGC. **slow / medium / fast** = velocidad de respuesta. Para SSB se recomienda *slow* o *medium*; para AM con señales estables, *off* o *slow*. |
| **▶ ACTIVAR / ■ DETENER** | Inicia o detiene el procesamiento en tiempo real. Al activar, el audio fluye por todo el pipeline. |
| **Bypass** | Pasa el audio directo de entrada a salida sin ningún procesamiento. Útil para comparar el sonido con y sin la aplicación activa. |

---

## Capítulo 3 — Módulos Activos

**Ubicación:** Pestaña Principal → grupo "Módulos activos"

### Descripción

Cada casilla de verificación activa o desactiva un módulo del pipeline de forma independiente y en tiempo real. El audio sigue fluyendo — simplemente el módulo es bypaseado cuando está desactivado.

### Módulos disponibles

| Módulo | Cuándo activarlo |
|--------|-----------------|
| **Supresor de impulsos** | Siempre en bandas con QRN (tormentas, ruido industrial). Desactivar si la señal es limpia para ahorrar CPU. |
| **Filtro de paso de banda (pre)** | Casi siempre activo. Limita el espectro antes del cancelador. |
| **Filtro de paso de banda (post)** | Casi siempre activo junto con el pre. Limpia artefactos del procesamiento espectral. |
| **ANF — Cancela heterodinos y tonos** | Activar cuando se escuchen tonos constantes (pito, zumbido). Desactivar con señales de datos/digitales (PSK, FT8) ya que los tomaría por interferencia. |
| **Cancelador de ruido estacionario** | El módulo principal. Activar una vez aprendido el perfil de ruido. |
| **EQ Presencia** | Activar para mejorar la claridad de la voz con señales debilitadas o muy filtradas. |
| **Squelch de voz (con música no utilizar!)** | Solo para transmisiones de voz SSB/AM. Silencia el ruido entre transmisiones. **No usar con música** — produce subidas y bajadas de nivel indeseadas. |
| **Excitador armónico** | Para señales de voz opacas, sin brillo. Añade presencia. Comparar con y sin para decidir. |

---

## Capítulo 4 — Supresor de Impulsos

**Ubicación:** Pestaña Avanzada Ruido → grupo "Supresor de Impulsos"

### Descripción

Detecta y atenúa transientes cortos de alta energía: descargas atmosféricas (QRN), líneas de alta tensión, motores eléctricos y cualquier interferencia impulsiva. Opera **antes** del AGC y el cancelador de ruido, con dos niveles de detección en cascada.

- **Nivel 1 (trama de 10 ms):** detecta bursts de energía que duran varios milisegundos, típicos de descargas atmosféricas grandes.
- **Nivel 2 (micro-trama de 0,67 ms):** detecta impulsos muy cortos — frituras, crackles, encendido de dispositivos cercanos.

El indicador **Actividad** muestra en tiempo real cuántos impulsos por segundo está detectando (⚡ N /s).

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Umbral de trama (10 ms)** | 5× – 100× | 15× | Sensibilidad del detector de trama larga. Valor bajo = más agresivo (captura más impulsos pero puede afectar la voz). Valor alto = solo blanquea pulsos muy intensos. **Bajar** si quedan descargas audibles; **subir** si la voz suena recortada. |
| **Umbral micro (0,67 ms)** | 3× – 30× | 8× | Sensibilidad para frituras y crackles muy cortos. Funciona igual que el anterior pero a escala de microsegundos. |

### Valores recomendados por situación

| Situación | Umbral trama | Umbral micro |
|-----------|-------------|--------------|
| Banda limpia, sin QRN | 50× | 20× |
| QRN moderado | 15× | 8× |
| Tormenta eléctrica cercana | 8× | 5× |

---

## Capítulo 5 — Filtro de Paso de Banda

**Ubicación:** Pestaña Avanzada Audio → grupo "Filtros DSP"

### Descripción

Filtro Butterworth IIR que limita el ancho de banda del audio a las frecuencias útiles para la voz. Se aplica en **dos puntos** del pipeline:

- **Pre (antes del cancelador):** limita el espectro que el cancelador "aprende" como ruido. Evita que el cancelador intente suprimir energía fuera del rango vocal.
- **Post (después del cancelador):** elimina artefactos espectrales que el procesamiento STFT del cancelador puede introducir fuera de la banda útil.

Ambos se activan/desactivan de forma independiente desde **Módulos Activos**.

### Controles

| Control | Rango | Default AM | Default SSB | Descripción |
|---------|-------|-----------|-------------|-------------|
| **AM Hz inferior** | 50–1000 Hz | 300 Hz | — | Frecuencia de corte inferior para AM. |
| **AM Hz superior** | 1000–10000 Hz | 5000 Hz | — | Frecuencia de corte superior. Subir hasta 10 kHz para AM locales con audio de alta fidelidad. |
| **SSB Hz inferior** | 50–1000 Hz | — | 200 Hz | Corte inferior para SSB. |
| **SSB Hz superior** | 1000–5000 Hz | — | 3000 Hz | Corte superior para SSB. |
| **Orden del filtro** | 2 / 4 / 6 / 8 | 4 | 4 | Pendiente del filtro. Mayor orden = corte más abrupto = mejor rechazo fuera de banda, pero mayor latencia de fase. Para uso normal, orden 4 es adecuado. |

### Consejos

- Para **AM locales con buena música** o audio de calidad: subir el Hz superior hasta 7000–10000 Hz.
- Para **SSB DX** con mucho ruido: bajar el Hz inferior a 300–400 Hz y el superior a 2500 Hz para reducir el ruido de banda.
- Cambiar el orden del filtro requiere reiniciar el procesamiento (el botón se deshabilita mientras está activo).

---

## Capítulo 6 — ANF: Filtro de Muesca Espectral

**Ubicación:** Pestaña Avanzada Ruido → grupo "ANF"

### Descripción

El **ANF** (Adaptive Notch Filter) detecta automáticamente tonos fijos o casi fijos en el espectro — heterodinos, portadoras AM de estaciones adyacentes, zumbidos de red (50/60 Hz y sus armónicos) — y los atenúa sin afectar el audio de voz circundante.

El algoritmo compara la magnitud de cada bin FFT con la mediana de sus vecinos. Si un bin supera N veces el nivel del entorno, se considera un tono y se aplica una muesca (notch). No tiene estado entre frames, lo que lo hace muy reactivo pero también evita que "persiga" voces.

El indicador **Actividad** muestra cuántos tonos están siendo muescados en este momento.

> **Importante:** No usar ANF con señales digitales (FT8, PSK31, WSPR, etc.). Esas señales tienen estructura espectral que el ANF interpreta como tonos a eliminar.

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Sensibilidad** | 1,5× – 10× | 3,0× | Ratio mínimo bin/entorno para considerar un tono. **Bajar** (1,5–2,5×) para detectar tonos débiles que apenas sobresalen. **Subir** (5–10×) para ser más selectivo y solo eliminar interferencias muy fuertes. |
| **Profundidad** | 0% – 100% | 90% | Cuánto se atenúa el tono detectado. 100% = silencia completamente el bin. 50% = reduce 6 dB. Para heterodinos molestos, 90–100% es lo habitual. |

---

## Capítulo 7 — Cancelador de Ruido Estacionario

**Ubicación:** Pestaña Principal → grupo "Cancelación de Ruido Estacionario" y Pestaña Avanzada Ruido → grupo "Cancelación de Ruido"

### Descripción

Es el módulo central de la aplicación. Implementa un **filtro de Wiener Log-MMSE espectral** con estimador DD (Decision-Directed) que reduce el ruido estacionario de fondo — estático de banda, ruido blanco, ruido de propagación — preservando la voz.

El estimador Log-MMSE (Ephraim & Malah, 1985) calcula la ganancia óptima bin a bin minimizando la distorsión en escala logarítmica, que se alinea con la percepción auditiva. Esto produce menos "metalicidad" residual en la voz respecto al Wiener clásico, especialmente en señales débiles.

### Modos de estimación de ruido

El cancelador ofrece dos modos, seleccionables desde el selector **Modo:** en la pestaña Principal:

**Perfil estático** (modo manual)
El algoritmo aprende una "foto" del ruido de fondo durante unos segundos y la usa como referencia fija. Ideal cuando el ruido de banda es muy estable.

1. **Buscar un momento sin señal** — cuando la estación no está transmitiendo.
2. Pulsar **⏺ Aprender ruido** y esperar 3–5 segundos.
3. Pulsar **⏹ Detener** — el perfil queda guardado y se aplica.
4. Si las condiciones cambian mucho, repetir el proceso.
5. **Borrar perfil** reinicia la referencia.

**Adaptativo (MCRA)** (modo automático)
El algoritmo estima el piso de ruido continuamente en tiempo real, sin necesidad de aprendizaje manual. Se calibra en ~200ms al activar el procesamiento y se adapta automáticamente cuando cambian las condiciones de propagación, aparece QRM o varía el ruido de banda.

- No requiere intervención del usuario — funciona solo.
- Los botones Aprender/Borrar no aparecen (no aplican en este modo).
- El indicador de estado cambia de "calibrando..." a "estimando en tiempo real" una vez listo.
- **Recomendado** para sesiones largas de escucha donde las condiciones de banda varían.

### Indicadores en tiempo real (Avanzada Ruido)

| Indicador | Descripción |
|-----------|-------------|
| **Reducción (dB)** | Cuánto está reduciendo el ruido en este momento. Verde = reducción fuerte (>10 dB). Amarillo = reducción moderada. |
| **Voz (%)** | Probabilidad de que el frame actual contenga voz. Útil para calibrar el Squelch. |
| **Preview: escuchar ruido eliminado** | Invierte la salida para escuchar solo lo que se está eliminando. Útil para verificar que no se esté eliminando voz. |

### Controles avanzados (Pestaña Avanzada Ruido)

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Intensidad** | 0% – 100% | 70% | Cuánta reducción se aplica sobre los gains calculados. **0%** = sin reducción (audio pasa sin cambios). **100%** = reducción plena. La escala es no lineal: valores medios (50–70%) ya producen una reducción perceptible, mientras que los bins de voz se ven mínimamente afectados en cualquier posición. Comenzar en 70% y subir según el nivel de ruido. |
| **Piso espectral** | 0,05 – 0,30 | 0,10 | Ganancia mínima que se aplica a cualquier bin, incluso el más ruidoso. 0,10 significa que nunca se silencia más del 90% de la energía de un bin. **Nunca bajar de 0,05** — valores muy bajos con Anti-gorgojeo alto producen gorgojeo severo. |
| **Anti-gorgojeo (β)** | 0% – 98% | 97% | Velocidad con que los gains retornan al piso después de detectar voz. Alto (97–98%) = transiciones suaves, sin gorgojeo. Bajo (<90%) = más reactivo pero con riesgo de gorgojeo audible. **No bajar de 90% salvo en casos excepcionales.** |
| **Velocidad de ataque** | 50% – 92% | 80% | Velocidad con que el cancelador "abre" los bins de voz cuando detecta una señal. Bajo (50–70%) = ataque rápido, consonantes más nítidas. Alto (>85%) = ataque suave, menos artefactos en transiciones. |

### Relación entre Piso y Anti-gorgojeo

Estos dos parámetros interactúan. La regla práctica:

| Situación | Piso | Anti-gorgojeo |
|-----------|------|---------------|
| Radio con buen S/N | 0,10 | 97% |
| Radio con ruido variable | 0,15 | 97–98% |
| Señal muy débil, mucho ruido | 0,15–0,20 | 98% |

Con **piso bajo + anti-gorgojeo bajo** el resultado es gorgojeo inevitable. Subir primero el piso y luego ajustar el anti-gorgojeo.

---

## Capítulo 8 — Squelch de Voz

**Ubicación:** Pestaña Avanzada Ruido → dentro del grupo "Cancelación de Ruido"

> ⚠️ **No usar con música.** El detector de voz está calibrado para voz humana. Con música produce subidas y bajadas repentinas del nivel de audio al ritmo de la dinámica musical.

### Descripción

Silencia completamente la salida cuando el cancelador de ruido no detecta voz humana. En SSB, entre transmisiones no hay portadora — solo ruido de banda — y el squelch elimina ese ruido residual que queda después de la reducción.

Funciona multiplicando la salida por la probabilidad de voz calculada internamente. Cuando hay voz, la señal pasa sin atenuación. Cuando no hay voz, la salida se reduce suavemente hasta el silencio.

El parámetro **Retención** evita que el squelch corte el final de las palabras o las frases breves, manteniendo el gate abierto algunos milisegundos después de que la voz desaparece.

**Requiere perfil de ruido aprendido** para funcionar.

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Umbral squelch** | 0,05 – 0,60 | 0,15 | Nivel mínimo de actividad de voz para abrir el gate. **Bajo (0,05–0,15):** abre con señales débiles, más sensible. **Alto (0,35–0,60):** solo abre con voz clara y fuerte. Ajustar observando el indicador **Voz (%)** en la misma pestaña. |
| **Retención** | 0 – 1000 ms | 500 ms | Tiempo que el gate permanece abierto después de que la voz desaparece. 500 ms es adecuado para SSB normal. Subir a 700–1000 ms para operadores con pausas largas entre palabras. |

### Calibración con el indicador Voz (%)

El indicador **Voz (%)** en el grupo muestra en tiempo real la actividad detectada. Para calibrar el umbral:

1. Escuchar una transmisión activa → el indicador sube a 50–100%.
2. En silencio entre transmisiones → el indicador cae a 0–15%.
3. Ajustar el **Umbral** para que esté entre esos dos valores (ej. 0,20 si en voz marca 70% y en silencio marca 5%).

---

## Capítulo 9 — EQ de Presencia

**Ubicación:** Pestaña Avanzada Audio → grupo "Voz"

### Descripción

Filtro ecualizador de pico (peaking EQ) centrado en la zona de frecuencias críticas para la inteligibilidad de la voz. El rango 1000–3000 Hz es donde el oído humano discrimina mejor las consonantes — las que hacen que la voz sea inteligible.

Útil cuando la voz suena "apagada" o "nasal" después del procesamiento, o cuando la condición de propagación atenúa las frecuencias altas.

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Frecuencia** | 1000 – 2000 Hz | 2000 Hz | Centro del pico de realce. 2000 Hz enfatiza consonantes (s, t, f). 1000–1500 Hz da más "cuerpo" a la voz masculina. |
| **Ganancia** | -3 dB a +10 dB | 0 dB | Cuánto se amplifica la frecuencia central. Con 0 dB el módulo no tiene efecto aunque esté activo. Comenzar con +3 a +6 dB y ajustar por preferencia. |
| **Q (selectividad)** | 0,2 – 2,0 | 0,7 | Anchura del pico. Q bajo (0,2–0,4) = pico ancho, afecta una banda amplia. Q alto (1,5–2,0) = pico estrecho, muy selectivo. Para voz de radio, Q entre 0,5 y 1,0 es lo habitual. |

---

## Capítulo 10 — Excitador Armónico

**Ubicación:** Pestaña Avanzada Audio → grupo "Excitador Armónico"

### Descripción

Genera armónicos artificiales en la zona de 1–4 kHz para recuperar la sensación de "brillo" y "presencia" que se pierde con los filtros de paso de banda y la reducción de ruido.

El proceso toma el contenido por encima de 1 kHz, lo satura suavemente con la función matemática *tanh* (que genera 2do y 3er armónico), extrae solo los armónicos generados (sin la señal original) y los mezcla de vuelta al audio a bajo nivel.

El efecto es similar al de un excitador analógico: la voz suena más "aérea", con más ataque en las consonantes, sin aumentar el nivel físico del audio.

**No es un sustituto de la EQ de presencia** — son complementarios. La EQ amplifica lo que existe; el excitador genera energía nueva correlacionada con la voz presente.

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Drive** | 1,0× – 10,0× | 2,0× | Cuánta saturación se aplica antes de extraer los armónicos. **Bajo (1–3×):** genera principalmente 2do armónico, efecto sutil. **Alto (6–10×):** más armónicos de orden superior, efecto más pronunciado pero puede sonar artificial. Comenzar en 2,0×. |
| **Mezcla** | 0% – 100% | 30% | Cuánto de los armónicos generados se suma al audio original. **20–40%** es la zona útil — notable pero sin sonar artificial. Por encima de 60% el efecto se vuelve muy pronunciado. |

### Síntomas y ajuste

| Síntoma | Ajuste |
|---------|--------|
| La voz suena "metálica" o "chirrillante" | Bajar Drive (a 1,5–2,0×) |
| El efecto no se nota | Subir Mezcla (a 40–50%) |
| Agrega ruido de fondo | Verificar que el cancelador esté activo — el excitador amplifica también los armónicos del ruido |

---

## Capítulo 11 — Niveles y Ganancia

**Ubicación:** Pestaña Principal → grupo "Niveles y Ganancia"

### Descripción

Controla los niveles de entrada y salida, y protege contra picos de audio. Los medidores VU muestran el nivel en dB en tiempo real para entrada y salida.

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Entrada** | -20 dB a +20 dB | 0 dB | Amplifica o atenúa el audio antes del pipeline. Subir si la señal de la radio llega débil (el VU de entrada está en el rango -20 a -10 dB). Bajar si llega saturada (VU en rojo). |
| **Salida** | -20 dB a +20 dB | 0 dB | Amplifica o atenúa la salida del pipeline. Útil para compensar la reducción de nivel que produce el cancelador de ruido — al suprimir el ruido, el audio percibido baja porque el ruido ya no suma al nivel total. Subir 3–6 dB para compensar. |
| **Límite de picos** | -12 dB a 0 dB | -1 dB | Nivel máximo permitido a la salida. Evita distorsión por saturación. -1 dB es suficiente para evitar clipping sin comprimir el audio. |

### Indicador del limitador de picos

Debajo del slider **Límite de picos** aparece un indicador en tiempo real:

- **—** (gris): el limitador no está actuando — el nivel de salida está por debajo del umbral configurado.
- **ACTIVO  -X.X dB** (naranja): el limitador está reduciendo picos leves (menos de 3 dB de reducción).
- **ACTIVO  -X.X dB** (rojo): el limitador está trabajando intensamente (más de 3 dB de reducción) — considerar bajar la ganancia de salida o el límite de picos.

### Medidores VU

- **Verde** (-20 a -6 dB): nivel óptimo.
- **Amarillo** (-6 a -3 dB): nivel alto, normal en picos de voz.
- **Rojo** (por encima de -3 dB): saturación — reducir la ganancia de entrada.

---

## Configuración recomendada para empezar

### SSB en bandas HF (14–28 MHz)

| Módulo | Estado | Notas |
|--------|--------|-------|
| Supresor de impulsos | ✅ Activo | Umbral trama 15×, micro 8× |
| Filtro paso de banda pre | ✅ Activo | SSB: 200–3000 Hz |
| Filtro paso de banda post | ✅ Activo | Igual que pre |
| ANF | ✅ Activo | Sensibilidad 3,0×, profundidad 90% |
| Cancelador de ruido | ✅ Activo | Aprender perfil primero |
| Squelch | ✅ Activo | Umbral 0,20, retención 300 ms |
| EQ Presencia | ✅ Activo | +4 dB a 2000 Hz |
| Excitador armónico | ⬜ Opcional | Drive 2,0×, mezcla 25% |

### AM (ondas medias o cortas)

| Módulo | Estado | Notas |
|--------|--------|-------|
| Supresor de impulsos | ✅ Activo | Umbral trama 20×, micro 10× |
| Filtro paso de banda pre | ✅ Activo | AM: 300–5000 Hz (música: hasta 10000 Hz) |
| Filtro paso de banda post | ✅ Activo | Igual que pre |
| ANF | ⬜ Opcional | Solo si hay heterodinos audibles |
| Cancelador de ruido | ✅ Activo | Aprender perfil primero |
| Squelch | ❌ No usar | Produce bombeo con música |
| EQ Presencia | ⬜ Opcional | Solo si la voz suena apagada |
| Excitador armónico | ⬜ Opcional | Con moderación |

---

## Capítulo 12 — Visualizador de Espectro

**Ubicación:** Pestaña Espectro

### Descripción

Muestra en tiempo real la distribución de energía por frecuencia (espectrograma) de la señal de entrada y de salida del pipeline. Permite ver de un vistazo cuánto ruido está siendo eliminado en cada banda de frecuencia y verificar que la voz no está siendo afectada.

El visualizador opera a ~15 cuadros por segundo. Para reducir el costo de CPU, se pausa automáticamente cuando la pestaña Espectro no está visible.

### Curvas disponibles

| Curva | Color | Descripción |
|-------|-------|-------------|
| **Entrada** | Azul | Señal antes del cancelador de ruido (después del filtro de paso de banda y el ANF). |
| **Salida** | Verde | Señal final procesada, tal como sale al dispositivo de audio. |
| **Lo cancelado** | Naranja (relleno) | Área entre la curva de entrada y la de salida — energía que el cancelador está restando. Cuanto mayor el área naranja, más ruido está siendo eliminado. |
| **Piso de ruido** | Amarillo punteado | Perfil espectral aprendido por el cancelador. Aparece al aprender el perfil desde la pestaña Principal. Representa "cómo suena el ruido de fondo" bin a bin. |

Cada curva puede mostrarse u ocultarse de forma independiente con las casillas de la barra superior.

### Controles

**Casillas de visibilidad (barra superior)**

Activan o desactivan cada curva sin afectar el procesamiento de audio.

**Aprender / borrar el piso de ruido**

El piso amarillo se captura desde el botón **⏺ Aprender ruido** de la pestaña Principal. Al detener el aprendizaje, la línea queda fija mostrando el perfil activo. El botón **Borrar perfil** también borra la línea del espectro.

**Sliders de zoom**

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Máx Y** | -60 dBFS a 0 dBFS | 0 dBFS | Ajusta el techo del eje vertical. Bajar (ej. -20 dBFS) comprime la escala y hace más visibles las diferencias entre curvas cuando la señal es débil. El valor se guarda automáticamente. |
| **Máx X** | 1 kHz a 12 kHz | 12 kHz | Ajusta el límite derecho del eje de frecuencias. Reducir a 3–4 kHz hace zoom en la zona vocal y permite ver mejor los detalles en esa banda. El valor se guarda automáticamente. |

### Interpretación práctica

**Reducción visible pero voz limpia:**
- El área naranja cubre principalmente las frecuencias de ruido de fondo (distribución uniforme en toda la banda).
- La curva verde queda por debajo de la azul en zonas de ruido, pero las dos convergen en los picos de voz.

**El cancelador está suprimiendo voz (demasiado agresivo):**
- El área naranja es grande incluso en los picos de voz.
- Reducir **Intensidad** o subir **Piso espectral** en la pestaña Avanzada Ruido.

**El cancelador no está haciendo nada:**
- Las curvas azul y verde se solapan completamente — sin área naranja.
- Verificar que hay perfil de ruido aprendido y que el módulo **Cancelador de ruido estacionario** está activo.

**Verificar el preview "escuchar ruido eliminado":**
- Activar el checkbox **Preview: escuchar ruido eliminado** (pestaña Principal) y observar el espectro.
- Lo que se escucha debe coincidir con el área naranja. Si se ven picos de voz en el área naranja, el cancelador está tocando la voz — subir el **Piso espectral**.

---

## Persistencia de configuración

Todos los ajustes se guardan automáticamente al cerrar la aplicación y se restauran al volver a abrirla. El archivo `settings.json` se crea junto al ejecutable. Para volver a los valores de fábrica, simplemente borrar ese archivo.

Cada pestaña avanzada tiene un botón **"↺ Restaurar valores por defecto"** que reinicia solo los controles de esa pestaña sin afectar el resto de la configuración.

Los valores de los sliders **Máx Y** y **Máx X** del visualizador de espectro también se guardan en `settings.json` junto con el resto de la configuración.

---

*Reductor de Ruido Radio — versión 1.2*

# Reductor de Ruido Radio — Manual de Usuario

**Versión 1.2**

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
- No corrige el nivel de los desvanecimientos (fading) de propagación — aunque la **Compensación fading HF** (Cap. 7) evita que el cancelador de ruido se desajuste durante los fades.
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
          ├─ sub: Refuerzo de pitch SSB (opcional)
          └─ sub: Post-filtro espectral  (opcional)
                           │
               [ Squelch de Voz  (opcional) ]
          Silencia la salida entre transmisiones
                           │
            [ Filtro de Paso de Banda  ── POST ]
         Limpia fugas espectrales post-procesado
                           │
              [ EQ de Voz: presencia + cuerpo ]
         Realce de consonantes y cuerpo de la voz
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
| **AGC** | Control Automático de Ganancia. **off** = sin AGC. **slow / medium / fast** = velocidad de respuesta. **Custom** = parámetros ajustables a mano (ver más abajo). Para SSB se recomienda *slow* o *medium*; para AM con señales estables, *off* o *slow*. |
| **▶ ACTIVAR / ■ DETENER** | Inicia o detiene el procesamiento en tiempo real. Al activar, el audio fluye por todo el pipeline. |
| **Bypass** | Pasa el audio directo de entrada a salida sin ningún procesamiento. Útil para comparar el sonido con y sin la aplicación activa. |

### AGC Personalizado (Custom)

**Ubicación:** Pestaña Avanzada Audio → grupo "AGC Personalizado"

Al seleccionar **Custom** en el combo AGC se habilitan cuatro sliders que permiten ajustar el comportamiento del AGC a mano. Con cualquier otro preset los sliders quedan deshabilitados (los presets usan sus valores fijos). Todos los cambios se aplican en tiempo real.

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Nivel objetivo** | −30 a −6 dBFS | −20 | Nivel RMS al que el AGC lleva la señal. Más alto = salida más fuerte, pero menos margen antes del limitador de picos. |
| **Ganancia máxima** | 0 a +60 dB | +36 | Tope de amplificación para señales débiles. Bajarlo evita que el AGC levante el ruido de fondo en pausas largas sin señal. |
| **Ataque** | 1 a 200 ms | 25 | Cuán rápido baja la ganancia ante una señal fuerte. Rápido protege de picos pero puede "bombear" con voz SSB; lento es más natural. |
| **Release** | 100 a 8000 ms | 2000 | Cuán rápido recupera la ganancia al caer la señal. Lento = estable con QSB profundo; rápido = sigue el fading pero respira más. |

**Guía rápida:** los presets equivalen aproximadamente a — *fast*: ataque 5 ms / release 500 ms; *medium*: 25 ms / 2000 ms; *slow*: 100 ms / 5000 ms (todos con objetivo −20 dBFS y ganancia máxima +36 dB). Partir del preset más parecido a lo que se busca y ajustar desde ahí.

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
| &nbsp;&nbsp;&nbsp;↳ **Piso espectral perceptual** | Sub-módulo del cancelador. Reemplaza el piso fijo por una curva que varía con la frecuencia: eleva el piso en la zona vocal (~500 Hz, preserva la calidez de la voz) y lo baja en alta frecuencia (suprime más el soplido). Curva configurable en Avanzada Cancelador. |
| &nbsp;&nbsp;&nbsp;↳ **Post-filtro espectral** | Sub-módulo del cancelador. Elimina el "ruido musical" (pitidos intermitentes) que el Wiener deja como residuo. Activar cuando se note ese artefacto. Agresividad configurable en Avanzada Cancelador. |
| &nbsp;&nbsp;&nbsp;↳ **Refuerzo de pitch SSB** | Sub-módulo del cancelador. Para señales SSB muy débiles: detecta el tono fundamental de la voz y protege sus armónicos de ser suprimidos. Activar solo si la voz suena "fantasmal" con el cancelador al máximo. Sensibilidad configurable en Avanzada Cancelador. |
| &nbsp;&nbsp;&nbsp;↳ **Squelch de voz** | Sub-módulo del cancelador. Silencia completamente el audio entre transmisiones (gate binario, sin mute parcial). **No usar con música.** Indicador de nivel de voz y estado del gate en Avanzada Cancelador. |
| **EQ Voz (presencia + cuerpo)** | Dos bandas paramétricas: presencia (claridad, 1–2 kHz) y cuerpo (calidez, 150–800 Hz). Activar para modelar la voz con señales debilitadas o muy filtradas. |
| **Excitador armónico** | Para señales de voz opacas, sin brillo. Añade presencia. Comparar con y sin para decidir. |

---

## Capítulo 4 — Supresor de Impulsos

**Ubicación:** Pestaña Avanzada Impulsos → grupo "Supresor de Impulsos"

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

**Ubicación:** Pestaña Avanzada Impulsos → grupo "ANF"

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

**Ubicación:** Pestaña Principal → grupo "Cancelación de Ruido Estacionario" y Pestaña Avanzada Cancelador → grupo "Cancelador de Ruido"

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

**Memoria de piso ante squelch de portadora**

Cuando el squelch de la radio corta la portadora (silencio total entre transmisiones), el MCRA detecta automáticamente que la energía del frame cayó muy por debajo del piso de ruido estimado y **congela** todo el estado del estimador: no actualiza ni el suavizado espectral, ni el seguimiento de mínimos, ni el estimado de ruido `λ_d`. Al volver la señal, el algoritmo retoma exactamente desde el perfil memorizado — sin período de re-calibración ni ruido audible al inicio de la transmisión.

Este comportamiento es automático y no requiere ningún ajuste. Se activa cuando la señal cae más de 13 dB por debajo del piso estimado, lo que distingue un squelch real (portadora cortada) de una pausa normal entre palabras donde el ruido de banda sigue presente.

**Compensación de fading HF** (solo modo Adaptativo)

**Activar:** Pestaña Avanzada Cancelador → casilla "Compensación fading HF"

En onda corta con desvanecimiento ionosférico (QSB), la señal sube y baja de nivel varias veces por minuto. Sin compensación, esto produce dos problemas audibles:

1. Durante el fade, el estimador adaptativo interpreta la caída de señal como una bajada del piso de ruido y se re-calibra hacia abajo. Al volver la señal, el piso queda desfasado y se escucha ruido sin atenuar hasta que el estimador se reajusta (~800 ms).
2. El estimador de ganancia del Wiener sigue al nivel de señal con retraso: cuando la señal vuelve del fade, "llega tarde" y recorta el inicio de la voz arrastrando ruido.

La compensación ataca ambos problemas:

- **Congelamiento del estimador:** cuando detecta un cambio brusco de energía (≥5 dB en un frame, típico de una transición de fade), congela el estimado de piso de ruido por 200 ms. El piso pre-fade se preserva y al volver la señal se aplica de inmediato.
- **Release acelerado:** mientras la casilla está activa, la ganancia del Wiener responde a subidas de señal en ~20–30 ms en lugar de 100–150 ms. La voz que emerge del fade se abre sin retraso perceptible.

El indicador junto a la casilla muestra **FADE** (naranja) cuando hay un evento de fading activo y **ok** (gris) cuando la señal está estable. Si FADE aparece constantemente sin que haya desvanecimiento real, la señal tiene variaciones rápidas de nivel (p. ej. AM con modulación profunda) y conviene desactivar la casilla.

> **Cuándo activarla:** escucha de onda corta (SSB o AM DX) con fading perceptible, siempre en modo Adaptativo. En señales locales estables o en modo Perfil estático no tiene efecto útil.

### Indicadores en tiempo real (Avanzada Cancelador)

| Indicador | Descripción |
|-----------|-------------|
| **Reducción (dB)** | Cuánto está reduciendo el ruido en este momento. Verde = reducción fuerte (>10 dB). Amarillo = reducción moderada. |
| **Voz (%)** | Probabilidad de que el frame actual contenga voz (señal suavizada usada internamente por el Wiener). Para calibrar el Squelch, usar el indicador **Nivel de voz** del grupo Squelch (más reactivo). |
| **Preview: escuchar ruido eliminado** | Invierte la salida para escuchar solo lo que se está eliminando. Útil para verificar que no se esté eliminando voz. |

### Controles avanzados (Pestaña Avanzada Cancelador)

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Intensidad** | 0% – 100% | 70% | Cuánta reducción se aplica sobre los gains calculados. **0%** = sin reducción (audio pasa sin cambios). **100%** = reducción plena. La escala es no lineal: valores medios (50–70%) ya producen una reducción perceptible, mientras que los bins de voz se ven mínimamente afectados en cualquier posición. Comenzar en 70% y subir según el nivel de ruido. |
| **Piso espectral** | 0,05 – 0,30 | 0,10 | Ganancia mínima que se aplica a cualquier bin, incluso el más ruidoso. 0,10 significa que nunca se silencia más del 90% de la energía de un bin. **Nunca bajar de 0,05** — valores muy bajos con Anti-gorgojeo alto producen gorgojeo severo. |
| **Anti-gorgojeo (β)** | 90% – 99% (pasos de 0,1%) | 97% | Velocidad con que los gains retornan al piso después de detectar voz. Alto (97–99%) = transiciones suaves, sin gorgojeo. Bajo (90–95%) = más reactivo pero con riesgo de gorgojeo audible. La resolución fina de 0,1% permite calibrar con precisión en el extremo alto, donde cada décima cambia el release de forma audible (98,0% ≈ 0,5 s; 98,5% ≈ 0,7 s; 99,0% ≈ 1 s). El máximo elimina el gorgojeo más persistente pero puede dejar una "cola" de ruido tras cada transmisión — usarlo solo si 97–98% no alcanza. |
| **Velocidad de ataque** | 50% – 92% | 80% | Velocidad con que el cancelador "abre" los bins de voz cuando detecta una señal. Bajo (50–70%) = ataque rápido, consonantes más nítidas. Alto (>85%) = ataque suave, menos artefactos en transiciones. |

### Relación entre Piso y Anti-gorgojeo

Estos dos parámetros interactúan. La regla práctica:

| Situación | Piso | Anti-gorgojeo |
|-----------|------|---------------|
| Radio con buen S/N | 0,10 | 97% |
| Radio con ruido variable | 0,15 | 97–98% |
| Señal muy débil, mucho ruido | 0,15–0,20 | 98% |

Con **piso bajo + anti-gorgojeo bajo** el resultado es gorgojeo inevitable. Subir primero el piso y luego ajustar el anti-gorgojeo.

### Piso espectral perceptual

**Activar:** Módulos Activos → casilla "Piso espectral perceptual (curva de enmascaramiento auditivo)"  
**Ajustar:** Pestaña Avanzada Cancelador → grupo "Piso espectral perceptual"

El control **Piso espectral** estándar aplica la misma ganancia mínima a todas las frecuencias. Pero el oído no percibe el ruido residual por igual en todas las bandas: en la zona de las fundamentales vocales (~300–800 Hz) un piso algo más alto suena más natural y cálido, mientras que por encima de 3 kHz el ruido residual (soplido) es lo más molesto y conviene suprimirlo más.

Este módulo reemplaza el piso fijo por una curva con tres zonas:

- **Boost vocal:** el piso se eleva alrededor de la frecuencia central configurada (default 500 Hz). Preserva la calidez de la voz.
- **Zona neutra** (1–3 kHz): sin cambio — los formantes pasan con el piso base.
- **Rolloff de agudos:** por encima de la frecuencia de inicio configurada, el piso baja progresivamente. Suprime más el soplido de alta frecuencia.

**Indicadores en tiempo real:**

| Indicador | Descripción |
|-----------|-------------|
| **Piso vocal** | Valor del piso en la frecuencia de máximo boost, en % y en dB relativos al piso base. Ej.: "25% (+8.0 dB)" significa que en el centro vocal el piso es 0,25 mientras el base es 0,10. |
| **Activo** | Porcentaje de bins del espectro que el piso está reteniendo en este momento. **Si marca 0%, el módulo no está teniendo ningún efecto** — el Wiener ya está dando ganancias por encima del piso y mover los sliders no cambiará nada audible. Con ruido de banda presente, valores de 20–50% son normales. |

**Controles:**

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Amplitud boost vocal** | 0% – 250% | 75% | Cuánto se eleva el piso en la zona vocal respecto al piso base. 75% = suave, 150% = normal, 250% = máximo. Subir si la voz suena "fría" o hueca con el cancelador activo. |
| **Centro del boost** | 200 – 1200 Hz | 500 Hz | Frecuencia donde el boost es máximo. 400–600 Hz para voz masculina, 600–900 Hz para voz femenina. |
| **Inicio del rolloff** | 1000 – 6000 Hz | 3000 Hz | Frecuencia a partir de la cual el piso empieza a bajar. |
| **Profundidad del rolloff** | 0% – 70% | 55% | Cuánto baja el piso en el extremo agudo. Más profundidad = menos soplido residual, a costa de opacar levemente los agudos de la voz. |

> **Consejo:** usar el indicador **Activo** como guía. Si marca 0% de forma sostenida, el piso base (control "Piso espectral") ya está por debajo de las ganancias que calcula el Wiener y la curva perceptual no interviene — en ese caso el ajuste relevante es la Intensidad del cancelador, no esta curva.

### Post-filtro espectral

**Activar:** Módulos Activos → casilla "Post-filtro espectral (ruido musical residual)"  
**Ajustar:** Pestaña Avanzada Cancelador → grupo "Post-filtro espectral"

El filtro de Wiener, incluso bien configurado, puede dejar un tipo de artefacto muy particular llamado **ruido musical**: en lugar del ruido de fondo uniforme original, aparecen pitidos cortos intermitentes que varían aleatoriamente de bin en bin. Es el residuo de los bins que el VAD marcó como ruido pero que no fueron suprimidos del todo por el piso espectral.

El post-filtro aplica una segunda pasada sobre esos bins usando la misma información de probabilidad de voz: en los bins donde hay ruido residual (`p_speech ≈ 0`) la ganancia se reduce adicionalmente; en los bins de voz (`p_speech ≈ 1`) no se aplica ningún cambio.

**Indicador en tiempo real:**

| Indicador | Descripción |
|-----------|-------------|
| **Reducción extra** | Cuántos dB adicionales está eliminando el post-filtro en los bins de ruido, por encima de lo que ya hace el cancelador base. Verde cuando supera −5 dB, amarillo en la zona −0,5 a −5 dB, gris cuando no hay ruido activo o el módulo está desactivado. Permite verificar de un vistazo que el slider de agresividad está teniendo efecto real. |

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Agresividad** | 0,0 – 4,0 | 1,0 | Fuerza de la segunda pasada. **0** = desactivado (aunque el checkbox esté activo). **1** = moderado: los bins de ruido puro reciben `gain²` (duplica la reducción en dB). **2** = normal: `gain³`. **4** = máximo: `gain⁵` — silencio casi total en los bins de ruido. Empezar en 1,0 y subir según el indicador Reducción extra hasta que el ruido musical desaparezca. |

> **Nota:** Valores altos (>2,5) con señales de SNR muy bajo pueden producir supresión excesiva en los bordes de las transiciones de voz. Si la voz empieza a sonar recortada, reducir a 0,5–1,5.

### Refuerzo de pitch SSB

**Activar:** Módulos Activos → casilla "Refuerzo de pitch SSB (detección por autocorrelación)"  
**Ajustar:** Pestaña Avanzada Cancelador → slider "Protección de armónicos"

En señales SSB muy débiles enterradas en ruido, el cancelador de Wiener puede suprimir los armónicos de la voz junto con el ruido porque el VAD no logra distinguirlos. El resultado es una voz que suena "fantasmal", de tono cambiante o con pérdida de naturalidad.

Este módulo detecta en tiempo real el **tono fundamental** (f0) de la voz mediante autocorrelación sobre una ventana de 42ms, busca f0 en el rango 80–400 Hz, y levanta la probabilidad de voz (`p_speech`) en todos los bins que corresponden a armónicos de ese f0. El cancelador entonces los trata como voz y los deja pasar.

- La detección funciona con un **umbral de confianza**: si la señal no es suficientemente periódica (no hay voz clara), no modifica nada.
- **Hold de 3 frames:** ante breves gaps de detección, el último f0 válido se mantiene para evitar fluctuaciones.
- **Solo para SSB.** En AM con ruido, el ensanchamiento de banda hace que la detección de f0 sea poco fiable.

**Indicador en tiempo real:**

| Indicador | Descripción |
|-----------|-------------|
| **Pitch detectado** | f0 de la voz en Hz, en tiempo real. Verde = detección activa (la máscara de armónicos está protegiendo la voz). "sin detección" (gris) = no hay señal periódica — el módulo está en passthrough. Con voz SSB clara debería marcar un valor estable en 80–400 Hz; si fluctúa erráticamente o nunca detecta, la señal es demasiado ruidosa o el clarificador de la radio está desajustado. |

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Protección de armónicos** | 0% – 100% | 70% | Cuánto se eleva `p_speech` en los bins armónicos. **70%** es el punto de equilibrio: protege la voz sin degradar la supresión del ruido. **>85%**: bins de armónicos casi nunca se suprimen — útil para señales muy débiles. **<40%**: efecto mínimo. |

> **Cuándo activarlo:** cuando la voz suena "fantasmal" o "robótica" con el cancelador en modo MCRA o con intensidad alta, y la señal es SSB DX débil. En condiciones normales, dejarlo desactivado.

---

## Capítulo 8 — Squelch de Voz

**Ubicación:** Pestaña Principal → Módulos Activos → sub-módulo "↳ Squelch de voz" (bajo el Cancelador)  
**Configuración avanzada:** Pestaña Avanzada Cancelador → grupo "Squelch de Voz"

> ⚠️ **No usar con música.** El detector de voz está calibrado para voz humana. Con música produce subidas y bajadas repentinas del nivel de audio al ritmo de la dinámica musical.

### Descripción

Silencia completamente la salida cuando el cancelador de ruido no detecta voz humana. En SSB, entre transmisiones no hay portadora — solo ruido de banda — y el squelch elimina ese ruido residual que queda después de la reducción.

Funciona como un **gate binario**: cuando se detecta voz, el audio pasa sin modificación; cuando no hay voz (y expira el tiempo de retención), la salida se silencia con un breve rampado de ~10 ms para evitar clicks. El cierre es completo — no hay audio residual ni gorgojeo.

El parámetro **Retención** evita que el squelch corte el final de las palabras o las frases breves, manteniendo el gate abierto algunos milisegundos después de que la voz desaparece.

**Requiere el Cancelador de ruido estacionario activo** — el detector de voz vive dentro del cancelador. Si el cancelador está desactivado, el squelch queda en bypass (el audio pasa siempre). Además necesita perfil de ruido aprendido (modo estático) o el período de calentamiento del MCRA (~200 ms).

### Indicadores en tiempo real (grupo Squelch, Avanzada Cancelador)

| Indicador | Descripción |
|-----------|-------------|
| **Nivel de voz** | Porcentaje de actividad vocal detectada en el frame actual, con respuesta rápida (~20 ms). Gris = ruido puro. Amarillo = señal marginal. Azul = voz detectada, gate va a abrir. |
| **Gate** | Estado actual del gate: **ABIERTO** (verde, audio pasa) o **CERRADO** (gris, silencio). Permanece ABIERTO durante el período de Retención tras fin de la voz. |

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Umbral squelch** | 5% – 100% | 15% | Nivel mínimo de actividad de voz para abrir el gate. La misma escala que el indicador **Nivel de voz**: observar cuánto marca con solo ruido y poner el umbral por encima. **Bajo (5–15%):** más sensible, abre con señales débiles — para bandas tranquilas. **Alto (65–90%):** necesario en bandas ruidosas, donde el ruido fluctuante puede marcar 50–60% por sí solo. |
| **Retención** | 0 – 1000 ms | 500 ms | Tiempo que el gate permanece abierto después de que la voz desaparece. 500 ms es adecuado para SSB normal. Subir a 700–1000 ms para operadores con pausas largas entre palabras. |

### Calibración

El indicador **Nivel de voz** y el estado del **Gate** en la pestaña Avanzada Cancelador son la herramienta principal de calibración:

1. **Con solo ruido de banda** (sin transmisión) → anotar cuánto marca "Nivel de voz". En bandas tranquilas será 5–15%; en bandas con ruido fuerte y fluctuante puede llegar a 50–60% — es normal: el detector mide variaciones de energía y el ruido atmosférico varía.
2. **Con transmisión activa** → "Nivel de voz" sube hacia 80–100% y "Gate: ABIERTO".
3. Ajustar el **Umbral** entre esos dos valores, más cerca del nivel de ruido (ej.: ruido 60% y voz 100% → umbral 70–75%; ruido 10% y voz 80% → umbral 20–30%).

> **Si el gate nunca cierra:** el nivel con solo ruido está por encima del umbral. Subir el umbral hasta superarlo — para eso el control llega hasta 100%.

> **Nota de temporización:** tras el fin de la voz, el indicador baja en ~100 ms; luego el gate permanece ABIERTO durante la Retención configurada y finalmente cierra. Si el gate cierra demasiado pronto cortando finales de palabras, aumentar la Retención.

---

## Capítulo 9 — EQ de Voz (Presencia + Cuerpo)

**Ubicación:** Pestaña Avanzada Audio → grupo "Voz"  
**Activar:** Módulos Activos → casilla "EQ Voz (presencia + cuerpo)"

### Descripción

Dos filtros ecualizadores de pico (peaking EQ) independientes que trabajan sobre las dos zonas que definen el carácter de la voz:

- **Cuerpo (150–800 Hz):** la zona de las fundamentales de la voz. Reforzarla da calidez, peso y "cuerpo" — útil cuando la voz suena delgada o telefónica, algo habitual después del filtrado de paso de banda y la reducción de ruido.
- **Presencia (1000–2000 Hz):** la zona donde el oído discrimina mejor las consonantes. Reforzarla da claridad e inteligibilidad — útil cuando la voz suena "apagada" o la propagación atenúa los agudos.

Ambas bandas pueden usarse a la vez: cuerpo +4 dB y presencia +4 dB producen una voz más llena y clara que cualquiera de las dos por separado. Cada banda con ganancia 0 dB queda en passthrough exacto (sin costo de procesamiento).

### Controles

| Control | Rango | Default | Descripción |
|---------|-------|---------|-------------|
| **Frecuencia de cuerpo** | 150 – 800 Hz | 350 Hz | Centro del pico de cuerpo. 250–400 Hz para voz masculina, 400–600 Hz para voz femenina. El ancho es fijo (Q 0,9 — aproximadamente una octava). |
| **Cuerpo (ganancia)** | -3 dB a +10 dB | 0 dB | Cuánto se refuerza el cuerpo de la voz. +3 a +5 dB es la zona útil; más de +6 dB puede sonar "tubular". También admite valores negativos para atenuar un exceso de graves. |
| **Frecuencia de presencia** | 1000 – 2000 Hz | 2000 Hz | Centro del pico de realce. 2000 Hz enfatiza consonantes (s, t, f). 1000–1500 Hz refuerza la zona media. |
| **Presencia (ganancia)** | -3 dB a +10 dB | 0 dB | Cuánto se amplifica la frecuencia central. Comenzar con +3 a +6 dB y ajustar por preferencia. |
| **Q (selectividad)** | 0,2 – 2,0 | 0,7 | Anchura del pico de presencia. Q bajo (0,2–0,4) = pico ancho, afecta una banda amplia. Q alto (1,5–2,0) = pico estrecho, muy selectivo. Para voz de radio, Q entre 0,5 y 1,0 es lo habitual. |

> **Consejo:** si la voz pierde cuerpo al activar el cancelador de ruido, probar primero el **Piso espectral perceptual** (Cap. 7), que evita la pérdida en origen. El EQ de cuerpo compensa después del hecho — ambos enfoques se complementan.

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
| Cancelador de ruido | ✅ Activo | Aprender perfil primero (o modo Adaptativo) |
| ↳ Piso espectral perceptual | ⬜ Opcional | Activar si la voz suena fría o hueca |
| ↳ Post-filtro espectral | ⬜ Opcional | Activar si se escuchan pitidos intermitentes residuales |
| ↳ Refuerzo de pitch SSB | ⬜ Opcional | Solo para señales SSB DX muy débiles |
| Compensación fading HF | ⬜ Opcional | Activar con QSB perceptible (solo modo Adaptativo) |
| Squelch | ✅ Activo | Umbral 15%, retención 300 ms |
| EQ Voz | ✅ Activo | Presencia +4 dB a 2000 Hz; cuerpo +3 dB a 350 Hz si la voz suena delgada |
| Excitador armónico | ⬜ Opcional | Drive 2,0×, mezcla 25% |

### AM (ondas medias o cortas)

| Módulo | Estado | Notas |
|--------|--------|-------|
| Supresor de impulsos | ✅ Activo | Umbral trama 20×, micro 10× |
| Filtro paso de banda pre | ✅ Activo | AM: 300–5000 Hz (música: hasta 10000 Hz) |
| Filtro paso de banda post | ✅ Activo | Igual que pre |
| ANF | ⬜ Opcional | Solo si hay heterodinos audibles |
| Cancelador de ruido | ✅ Activo | Aprender perfil primero (o modo Adaptativo) |
| ↳ Piso espectral perceptual | ⬜ Opcional | Activar si la voz suena fría o hueca |
| ↳ Post-filtro espectral | ⬜ Opcional | Activar si quedan pitidos residuales |
| ↳ Refuerzo de pitch SSB | ❌ No usar | No fiable con la banda ancha de AM |
| Compensación fading HF | ⬜ Opcional | Solo onda corta con QSB (modo Adaptativo); en AM local con música puede disparar en falso |
| Squelch | ❌ No usar | Produce bombeo con música |
| EQ Voz | ⬜ Opcional | Presencia si la voz suena apagada; cuerpo si suena delgada |
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
| **Piso de ruido** | Amarillo punteado | Perfil espectral usado por el cancelador. Representa "cómo suena el ruido de fondo" bin a bin. En modo **Perfil estático** aparece automáticamente cuando hay perfil (aprendido en la sesión o cargado desde una sesión anterior). En modo **Adaptativo (MCRA)** se actualiza cada 500 ms con el estimado en tiempo real. |

Cada curva puede mostrarse u ocultarse de forma independiente con las casillas de la barra superior.

### Controles

**Casillas de visibilidad (barra superior)**

Activan o desactivan cada curva sin afectar el procesamiento de audio.

**Aprender / borrar el piso de ruido**

En modo Perfil estático, el piso amarillo se captura desde el botón **⏺ Aprender ruido** de la pestaña Principal y queda fijo mostrando el perfil activo — incluso tras reiniciar el procesamiento o la aplicación, mientras el perfil exista. El botón **Borrar perfil** también borra la línea del espectro. En modo Adaptativo la línea se actualiza sola, sin intervención.

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
- Reducir **Intensidad** o subir **Piso espectral** en la pestaña Avanzada Cancelador.

**El cancelador no está haciendo nada:**
- Las curvas azul y verde se solapan completamente — sin área naranja.
- Verificar que hay perfil de ruido aprendido y que el módulo **Cancelador de ruido estacionario** está activo.

**Verificar el preview "escuchar ruido eliminado":**
- Activar el checkbox **Preview: escuchar ruido eliminado** (pestaña Principal) y observar el espectro.
- Lo que se escucha debe coincidir con el área naranja. Si se ven picos de voz en el área naranja, el cancelador está tocando la voz — subir el **Piso espectral**.

---

## Capítulo 13 — Presets

**Ubicación:** Pestaña Presets

### Descripción

Un preset guarda una "foto" completa de la configuración DSP y de ganancia — todos los módulos, sliders y modos de las pestañas Principal y Avanzadas. Los dispositivos de audio y la posición de la ventana **no** forman parte del preset (son específicos de cada equipo).

Uso típico: un preset "SSB DX débil" con cancelador agresivo y pitch enhancement, otro "AM local" con squelch apagado y filtros anchos, y cambiar entre ellos con doble clic según lo que estés escuchando.

### Operaciones

| Botón | Acción |
|-------|--------|
| **Guardar como nuevo** | Crea un preset con el nombre escrito, capturando la configuración actual. |
| **Sobrescribir seleccionado** | Actualiza el preset seleccionado con la configuración actual. |
| **Cargar** (o doble clic) | Aplica el preset **en caliente** — sin reiniciar el audio. Todos los sliders y checkboxes de la UI se actualizan al instante. |
| **Eliminar / Renombrar** | Gestión de la lista. |

Los presets se guardan como archivos `.json` individuales en la carpeta `Presets/` junto al ejecutable — se pueden respaldar o copiar entre equipos.

### Preset activo y persistencia

La etiqueta **"Preset activo"** muestra el último preset cargado o guardado. Si después de cargarlo se modifica cualquier control, la etiqueta agrega el sufijo **"(modificado)"** — indica que lo que suena es el preset más tus retoques, no el preset puro.

Al cerrar y volver a abrir la aplicación:

- **Los valores se restauran exactamente como quedaron** (vía `settings.json`), incluyendo cualquier retoque posterior al preset.
- La etiqueta "Preset activo" recuerda el nombre, con "(modificado)" si los valores actuales difieren de los guardados en el preset.
- Para volver al preset puro descartando los retoques, simplemente cargarlo de nuevo.

---

## Persistencia de configuración

Todos los ajustes se guardan automáticamente al cerrar la aplicación y se restauran al volver a abrirla. El archivo `settings.json` se crea junto al ejecutable. Para volver a los valores de fábrica, simplemente borrar ese archivo.

Cada pestaña avanzada tiene un botón **"↺ Restaurar valores por defecto"** que reinicia solo los controles de esa pestaña sin afectar el resto de la configuración.

**Restaurar un slider individual:** hacer **clic derecho** sobre cualquier slider muestra un menú contextual con la opción *"↺ Restaurar por defecto (valor)"*. Permite volver al valor de fábrica de ese parámetro puntual sin tocar los demás.

Los valores de los sliders **Máx Y** y **Máx X** del visualizador de espectro también se guardan en `settings.json` junto con el resto de la configuración.

---

*Reductor de Ruido Radio — versión 1.2*

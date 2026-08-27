"""
dsp.gate — Gate de ruido por nivel, con ventana de retención.

Reemplaza al squelch de voz, que decidía con el VAD (`voice_prob_sq`). Ese
criterio tenía dos problemas de fondo:

  - **No se podía calibrar.** El umbral estaba en porcentaje de una probabilidad
    que no aparece en ninguna pantalla. Un control cuyo criterio no es observable
    sólo se ajusta por prueba y error.
  - **El VAD no es confiable con señal débil.** Se calcula sobre `snr_post`, que
    depende de λ_d: medido sobre grabaciones reales, marcaba 0,93 en subidas de
    ruido contra 0,59 en arranques de voz — invertido.

Dos decisiones de diseño, las dos medidas:

1. **Decide con el nivel de ENTRADA, actúa sobre la SALIDA.** Silenciar la
   entrada parece lo natural, pero deja al estimador de ruido midiendo el
   silencio que el propio gate fabrica: medido sobre una grabación real, un gate
   en la entrada hunde λ_d **9,5 dB**; el mismo gate aplicado a la salida lo deja
   idéntico. Y justamente cierra en las pausas, que son los únicos ratos en que
   MCRA puede medir el ruido. Por eso `process()` recibe por separado el nivel
   con el que decide y el audio sobre el que actúa.

2. **El umbral es ABSOLUTO, en dBFS.** El primer diseño lo hizo relativo al piso
   medido, buscando que se auto-calibrara al cambiar de banda. No funciona, y el
   motivo es estructural: la referencia tiene que ser el ruido, pero cualquier
   seguidor de piso o bien persigue a la señal —y entonces el gate cierra sobre la
   voz— o bien no sigue al ruido. Medido con voz continua: con umbral relativo de
   +6 dB el gate quedaba **cerrado el 100 % del tiempo**, atenuando todo 20 dB, y
   con un piso propio de subida frenada seguía igual, porque en HF el nivel de
   banda completa se mueve apenas ~5 dB entre voz y no-voz.

   Absoluto además es **observable**, que era el punto de reemplazar al squelch: se
   calibra mirando el VU de entrada. Lo que se pierde —portabilidad entre
   estaciones— se maneja como con el techo de ruido del AGC: es un ajuste por
   estación, viaja en el preset y viene desactivado de fábrica.

Del squelch se conserva lo que ya se había ganado: la retención (para no cortar
entre palabras), el **cierre progresivo** —ganancia plena en la primera mitad de
la retención y desvanecimiento en la segunda, contra la "cola de squelch" que se
arregló en la v1.3— y la rampa por frame, que evita clicks al abrir y cerrar.
"""
import numpy as np


class NoiseGate:
    """Gate por nivel: decide con la entrada, atenúa la salida."""

    def __init__(self, sample_rate: int = 48000):
        self._sr = sample_rate
        self._enabled = False
        self._threshold_db = -50.0   # dBFS: nivel de entrada al que el gate abre
        self._hold_ms = 300.0
        self._depth_db = 20.0        # cuánto atenúa con el gate cerrado
        self._hold_frames = 0
        self._hold_count = 0
        self._gain_prev = 1.0
        self._open = False
        self.set_hop(480)

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------

    def set_enabled(self, v: bool) -> None:
        self._enabled = bool(v)
        if not self._enabled:
            # Al apagarlo, el gate tiene que quedar ABIERTO: si no, el estado
            # interno sobrevive y el próximo encendido arranca cerrando.
            self._hold_count = 0
            self._gain_prev = 1.0
            self._open = True

    def set_threshold_db(self, v: float) -> None:
        """Nivel de entrada (dBFS) a partir del cual el gate abre.
        Clamp == rango del slider (invariante 1)."""
        self._threshold_db = float(np.clip(v, -80.0, -20.0))

    def set_depth_db(self, v: float) -> None:
        """Atenuación con el gate cerrado. 0 = no atenúa; el tope silencia.
        Atenuar en vez de mutear suena bastante más natural en HF."""
        self._depth_db = float(np.clip(v, 0.0, 60.0))

    def set_hold_ms(self, v: float) -> None:
        self._hold_ms = float(np.clip(v, 50.0, 2000.0))
        self._recalc_hold()

    def set_hop(self, hop: int) -> None:
        """El hold se expresa en frames — depende del hop (invariante 9)."""
        self._hop = int(hop)
        self._recalc_hold()

    def _recalc_hold(self) -> None:
        hop_ms = (self._hop / self._sr) * 1000.0
        self._hold_frames = max(1, round(self._hold_ms / hop_ms))

    def reset(self) -> None:
        self._hold_count = 0
        self._gain_prev = 1.0
        self._open = False

    # ------------------------------------------------------------------
    # Proceso
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def gain(self) -> float:
        """Ganancia aplicada en el último frame (para el indicador de la UI)."""
        return self._gain_prev

    def process(self, audio: np.ndarray, level_db: "float | None") -> np.ndarray:
        """Aplica el gate a `audio` (la SALIDA), decidiendo con `level_db` (el
        nivel de la ENTRADA, en dBFS).

        Sin nivel medido todavía queda ABIERTO: es preferible dejar pasar audio a
        mutear por no saber en qué nivel está la entrada.
        """
        if not self._enabled or level_db is None:
            self._open = True
            self._gain_prev = 1.0
            return audio

        abre = level_db >= self._threshold_db
        if abre:
            self._hold_count = self._hold_frames
        elif self._hold_count > 0:
            self._hold_count -= 1

        cerrado = 10.0 ** (-self._depth_db / 20.0)
        if abre:
            objetivo = 1.0
        else:
            # Ganancia plena durante la primera mitad de la retención (las pausas
            # entre palabras no se tocan) y desvanecimiento en la segunda. Sin
            # esto el fondo pasa a volumen pleno todo el hold y después corta de
            # golpe — la "cola de squelch" que se arregló en la v1.3.
            media = max(1, self._hold_frames // 2)
            frac = min(1.0, self._hold_count / media)
            objetivo = cerrado + (1.0 - cerrado) * frac

        self._open = objetivo > cerrado + 1e-6
        if objetivo != self._gain_prev:
            # Rampa dentro del frame: un escalón de ganancia es un click.
            rampa = np.linspace(self._gain_prev, objetivo, len(audio), dtype=np.float32)
            audio = (audio * rampa).astype(np.float32)
        elif objetivo != 1.0:
            audio = (audio * np.float32(objetivo)).astype(np.float32)
        self._gain_prev = objetivo
        return audio

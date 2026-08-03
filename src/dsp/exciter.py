import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


class AuralExciter:
    """
    Excitador armónico estilo Aphex.

    Toma la banda de legibilidad (1–3.5 kHz), le genera armónicos con una
    saturación tanh y mezcla SOLO los armónicos al original:

        h    = bandpass(x)
        s    = rms(h) / 0.25                     (escala: nivel de trabajo fijo)
        u    = h / s                             (entrada normalizada a la no linealidad)
        d    = tanh(drive·u)/drive − u           (residuo de la saturación)
        odd  = d − ⟨d,u⟩/⟨u,u⟩ · u               (se le quita el componente LINEAL)
        out  = x + mix · gate · lpf(s · odd)

    Tres correcciones sobre la versión v1.9.1, todas medidas:

    1. `tanh(d·h) − h` valía, para señal chica, `(d−1)·h` — un realce de agudos
       LINEAL, no armónicos. Medido con drive 2 / mix 0.3: +1.79 dB de ganancia
       plana sobre 1 kHz y el 3er armónico 58 dB abajo (inaudible). El excitador
       no excitaba: ecualizaba, y con nivel alto además comprimía (~0.6 dB) —
       brillo que sube y baja con el nivel.
    2. Dividir por `drive` no alcanza: a nivel alto el residuo todavía contiene
       fundamental (la compresión de la tanh), que atenuaba 2.3 dB. La proyección
       le resta a la rama TODO lo correlacionado con la entrada, así que queda
       solo lo que la entrada no tenía: armónicos. Medido: ±0.05 dB de fuga.
    3. Normalizar la ENTRADA (no la salida) hace el efecto independiente del nivel
       sin anular el control: normalizando la salida, `drive` dejaba de mover nada.
        drive → CANTIDAD y orden de los armónicos (suave 1 → agresivo 10)
        mix   → cuánto de esos armónicos se mezcla

    El LPF de 7 kHz mantiene los armónicos dentro de la banda útil de voz en vez
    de dejarlos llegar hasta Nyquist como fritura.

    Gate por VAD (`set_voice_gate`): el excitador corre al final del pipeline, así
    que sin gate levanta el ruido residual igual que la voz (medido en v1.9.1:
    +2.07 dB sobre 1.5–6 kHz con o sin voz — el siseo brillante entre palabras).
    Con el gate, sin voz no agrega nada (+0.01 dB).

    Nota: tanh es simétrica → genera solo armónicos IMPARES (H3, H5, H7), que es
    el timbre hueco/metálico clásico. Agregar pares (H2) requiere una no linealidad
    par, que además produce productos de diferencia en los graves (medido: −31 dB
    con la rama filtrada a 1.2 kHz). Queda como control de "carácter" a futuro.
    """

    _BAND_LO_HZ: float = 1000.0   # banda de trabajo: armónicos en la zona de legibilidad
    _BAND_HI_HZ: float = 3500.0
    _LP_HZ:      float = 7000.0   # techo de los armónicos generados
    _REF_RMS:    float = 0.25     # nivel de trabajo de la no linealidad
    _RMS_SMOOTH: float = 0.90     # EMA del RMS para la normalización (~100 ms @ 10 ms)
    _RMS_MIN:    float = 1e-6     # por debajo de esto no hay señal que excitar
    _GATE_SMOOTH: float = 0.70    # EMA del gate por VAD (~30 ms, sin clicks)
    _GATE_VP_THR: float = 0.30    # vp donde el gate ya está abierto del todo

    def __init__(self, sample_rate: int = 48000):
        self._drive:   float = 2.0
        self._mix:     float = 0.3
        self._enabled: bool  = True

        nyq = sample_rate / 2.0
        self._sos_band = butter(
            2, [self._BAND_LO_HZ / nyq, min(self._BAND_HI_HZ / nyq, 0.99)],
            btype='band', output='sos').astype(np.float64)
        self._sos_lp = butter(
            2, min(self._LP_HZ / nyq, 0.99), btype='low', output='sos').astype(np.float64)

        self._zi_band: np.ndarray | None = None
        self._zi_lp:   np.ndarray | None = None
        self._rms_h:   float = 0.0
        self._proj:    float = 0.0    # coef. de proyección suavizado (parte lineal)
        self._gate:    float = 1.0
        self._gate_target: float = 1.0

    def reset(self) -> None:
        self._zi_band = None
        self._zi_lp   = None
        self._rms_h   = 0.0
        self._proj    = 0.0
        self._gate    = 1.0
        self._gate_target = 1.0

    def set_drive(self, drive: float) -> None:
        self._drive = float(np.clip(drive, 1.0, 10.0))

    def set_mix(self, mix: float) -> None:
        self._mix = float(np.clip(mix, 0.0, 1.0))

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_voice_gate(self, voice_prob: float) -> None:
        """Probabilidad de voz del frame (0–1) o 1.0 para no gatear (sin cancelador,
        que es cuando el VAD no se actualiza — invariante 2)."""
        self._gate_target = float(np.clip(voice_prob / self._GATE_VP_THR, 0.0, 1.0))

    @property
    def gate(self) -> float:
        return self._gate

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if not self._enabled or self._mix == 0.0:
            return chunk

        x = chunk.astype(np.float64)

        # Gate suavizado por bloque (evita saltos audibles al abrir/cerrar)
        self._gate = (self._GATE_SMOOTH * self._gate
                      + (1.0 - self._GATE_SMOOTH) * self._gate_target)
        if self._gate < 1e-3:
            return chunk

        if self._zi_band is None:
            self._zi_band = sosfilt_zi(self._sos_band) * x[0]
        if self._zi_lp is None:
            self._zi_lp = sosfilt_zi(self._sos_lp) * 0.0

        h, self._zi_band = sosfilt(self._sos_band, x, zi=self._zi_band)

        # Nivel de trabajo fijo para la no linealidad (RMS con memoria entre bloques):
        # el efecto no depende del nivel de entrada, pero `drive` sí lo controla
        a = self._RMS_SMOOTH
        self._rms_h = a * self._rms_h + (1.0 - a) * float(np.sqrt(np.mean(h * h)))
        if self._rms_h < self._RMS_MIN:
            return chunk
        scale = self._rms_h / self._REF_RMS
        u = h / scale

        resid = np.tanh(self._drive * u) / self._drive - u

        # Quitar el componente LINEAL: lo que queda es lo que la entrada no tenía.
        # El coeficiente se suaviza entre bloques para no modular el timbre.
        den = float(np.dot(u, u))
        if den > 1e-20:
            self._proj = a * self._proj + (1.0 - a) * (float(np.dot(u, resid)) / den)
        odd = resid - self._proj * u

        harm, self._zi_lp = sosfilt(self._sos_lp, scale * odd, zi=self._zi_lp)

        return (x + (self._mix * self._gate) * harm).astype(np.float32)

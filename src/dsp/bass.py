import numpy as np


class BassSynth:
    """
    Recuperación de graves: sintetiza el FUNDAMENTAL de la voz cuando el filtro
    de la radio ya lo cortó.

    Por qué sintetizar y no ecualizar: un pasa-altos de 300 Hz —el típico de un
    filtro SSB— deja el fundamental de una voz masculina 14 a 38 dB abajo (medido:
    f0=200 Hz −14 dB, 150 Hz −24 dB, 120 Hz −32 dB, 100 Hz −38 dB). No queda
    energía que levantar, así que ninguna EQ puede recuperarlo: hay que generarlo.
    La EQ de Cuerpo sigue siendo la herramienta correcta cuando los graves SÍ
    están y solo hay que reforzarlos; esto es para cuando no están.

    El f0 y su confianza vienen de la autocorrelación que el NoiseProfiler ya
    calcula por frame (la misma que usan el refuerzo de pitch y el freeze de MCRA),
    así que no agrega análisis: solo un oscilador.

    Diseño:
      - Oscilador con fase continua entre bloques (sin clicks al cambiar f0).
      - f0 suavizado: los saltos de octava del detector no se escuchan como salto.
      - Amplitud atada al RMS de la señal: al 100% el fundamental queda en el
        nivel que tendría en una voz natural (medido f0/RMS ≈ 1.18 en voz
        sintética con armónicos 1/k; se usa 1.0 como referencia conservadora).
      - Envolvente con ataque/release propios: entra y sale suave con la voz.
      - Solo actúa con f0 por debajo de _F0_MAX_HZ: por encima el fundamental
        normalmente pasó el filtro y no hay nada que recuperar.
      - Umbral de confianza ALTO: un f0 mal detectado se escucha como retumbe.
    """

    _F0_MAX_HZ:  float = 300.0   # por encima de esto no es "recuperar graves"
    _CONF_THR:   float = 0.40    # confianza de autocorrelación mínima (alta a propósito)
    _F0_SMOOTH:  float = 0.70    # suavizado de f0 entre frames
    _ENV_ATTACK: float = 0.30    # sube en ~3 frames
    _ENV_RELEASE: float = 0.85   # baja en ~7 frames (cola natural, sin cortes)
    # Amplitud del fundamental respecto del RMS de la señal al 100%. Calibrado
    # para que al 100% el fundamental sintetizado quede en el nivel que tenía en la
    # voz original: con una voz de f0=120 Hz filtrada a 300 Hz (−62 dB en el
    # fundamental) el 100% lo devuelve a ≈ −31 dB, que es donde estaba antes del
    # filtro. El default del slider (50%) queda ~6 dB por debajo, que es el punto
    # de partida prudente.
    _REF_RATIO:  float = 2.2

    def __init__(self, sample_rate: int = 48000):
        self._sr      = float(sample_rate)
        self._enabled = False
        self._amount  = 0.5
        self._phase   = 0.0
        self._f0:  float | None = None
        self._env: float = 0.0
        self._target_f0:  float = 0.0
        self._target_amp: float = 0.0

    def reset(self) -> None:
        self._phase = 0.0
        self._f0    = None
        self._env   = 0.0
        self._target_f0  = 0.0
        self._target_amp = 0.0

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not enabled:
            self._env = 0.0

    def set_amount(self, amount: float) -> None:
        self._amount = float(np.clip(amount, 0.0, 1.0))

    def set_voice(self, f0: "float | None", confidence: float) -> None:
        """f0 y confianza del análisis de autocorrelación del frame (NoiseProfiler)."""
        if (f0 is not None and confidence >= self._CONF_THR
                and 0.0 < f0 <= self._F0_MAX_HZ):
            self._target_f0 = float(f0)
            self._target_amp = 1.0
        else:
            self._target_amp = 0.0

    @property
    def active(self) -> bool:
        """True mientras está sonando el fundamental sintetizado (para la UI)."""
        return self._env > 0.01

    @property
    def f0(self) -> "float | None":
        return self._f0

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if not self._enabled or self._amount <= 0.0:
            return chunk

        # Envolvente: ataque rápido, release suave (sin clicks al entrar/salir)
        coef = self._ENV_ATTACK if self._target_amp > self._env else self._ENV_RELEASE
        self._env = coef * self._env + (1.0 - coef) * self._target_amp
        if self._env < 1e-3 and self._target_amp == 0.0:
            self._env = 0.0
            return chunk

        if self._target_f0 > 0.0:
            self._f0 = (self._target_f0 if self._f0 is None
                        else self._F0_SMOOTH * self._f0
                        + (1.0 - self._F0_SMOOTH) * self._target_f0)
        if not self._f0:
            return chunk

        n = len(chunk)
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        amp = self._amount * self._REF_RATIO * rms * self._env
        if amp <= 0.0:
            return chunk

        # Fase continua entre bloques: sin esto, cada bloque arrancaría en 0 y
        # se escucharía un click por bloque.
        step = 2.0 * np.pi * self._f0 / self._sr
        ph = self._phase + step * np.arange(1, n + 1, dtype=np.float64)
        self._phase = float(ph[-1] % (2.0 * np.pi))

        return (chunk + (amp * np.sin(ph)).astype(np.float32)).astype(np.float32)

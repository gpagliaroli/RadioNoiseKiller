import numpy as np


class AGC:
    """
    Control Automático de Ganancia para señales de onda corta.

    Usa detección de envolvente RMS por bloque con dos constantes de tiempo:
    - Attack: cuánto tarda en reducir la ganancia ante señal fuerte (rápido)
    - Release: cuánto tarda en recuperar la ganancia al caer la señal (lento)

    La ganancia se interpola linealmente dentro de cada bloque para evitar
    discontinuidades audibles entre frames consecutivos.
    """

    PRESETS: dict = {
        "off":    None,
        "fast":   {"attack_ms":   5, "release_ms":   500},
        "medium": {"attack_ms":  25, "release_ms":  2000},
        "slow":   {"attack_ms": 100, "release_ms":  5000},
        # "custom" no está acá: usa self._custom (parámetros del usuario)
    }

    _TARGET_DBFS   = -20.0   # nivel RMS objetivo
    _MAX_GAIN_DB   =  36.0   # límite superior de ganancia (+36 dB = ×63)

    def __init__(self, sample_rate: int, hop_size: int):
        self._sr        = sample_rate
        self._hop       = hop_size
        self._target    = 10 ** (self._TARGET_DBFS / 20.0)
        self._max_gain  = 10 ** (self._MAX_GAIN_DB / 20.0)
        self._envelope  = 1e-6
        self._gain      = 1.0
        self._enabled   = False
        self._attack_k  = 0.0
        self._release_k = 0.0
        self._custom    = {
            "target_dbfs": self._TARGET_DBFS,
            "max_gain_db": self._MAX_GAIN_DB,
            "attack_ms":   25.0,
            "release_ms":  2000.0,
        }

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------

    def set_preset(self, preset: str) -> None:
        self._preset = preset
        params = self._custom if preset == "custom" else self.PRESETS.get(preset)
        if params is None:
            self._enabled = False
            self._gain    = 1.0
            return
        self._enabled    = True
        target_dbfs      = params.get("target_dbfs", self._TARGET_DBFS)
        max_gain_db      = params.get("max_gain_db", self._MAX_GAIN_DB)
        self._target     = 10 ** (target_dbfs / 20.0)
        self._max_gain   = 10 ** (max_gain_db / 20.0)
        bps              = self._sr / self._hop          # bloques por segundo
        self._attack_k   = 1.0 - np.exp(-1.0 / (params["attack_ms"]  / 1000.0 * bps))
        self._release_k  = 1.0 - np.exp(-1.0 / (params["release_ms"] / 1000.0 * bps))

    # Parámetros del preset "custom". Los clamps deben coincidir con los
    # rangos de los sliders en AdvancedAudioTab (invariante del proyecto).
    def set_custom_target(self, dbfs: float) -> None:
        self._custom["target_dbfs"] = float(np.clip(dbfs, -30.0, -6.0))
        self._refresh_custom()

    def set_custom_max_gain(self, db: float) -> None:
        self._custom["max_gain_db"] = float(np.clip(db, 0.0, 60.0))
        self._refresh_custom()

    def set_custom_attack(self, ms: float) -> None:
        self._custom["attack_ms"] = float(np.clip(ms, 1.0, 200.0))
        self._refresh_custom()

    def set_custom_release(self, ms: float) -> None:
        self._custom["release_ms"] = float(np.clip(ms, 100.0, 8000.0))
        self._refresh_custom()

    def _refresh_custom(self) -> None:
        """Re-aplica el preset custom en caliente si está activo."""
        if getattr(self, "_preset", "off") == "custom":
            self.set_preset("custom")

    def set_hop(self, hop_size: int) -> None:
        """Actualiza el tamaño de bloque y recalcula las constantes de tiempo."""
        if hop_size != self._hop:
            self._hop = hop_size
            self.set_preset(getattr(self, "_preset", "off"))

    # ------------------------------------------------------------------
    # Propiedades de diagnóstico
    # ------------------------------------------------------------------

    @property
    def gain_db(self) -> float:
        return 20.0 * np.log10(max(self._gain, 1e-10))

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------

    def process(self, samples: np.ndarray) -> np.ndarray:
        if not self._enabled:
            return samples

        gain_prev = self._gain

        # Envolvente RMS del bloque
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2) + 1e-12))

        if rms > self._envelope:
            self._envelope += self._attack_k  * (rms - self._envelope)
        else:
            self._envelope += self._release_k * (rms - self._envelope)

        desired = min(self._target / max(self._envelope, 1e-10), self._max_gain)

        # Reducción de ganancia: ataque rápido; recuperación: release lento
        k = self._attack_k if desired < self._gain else self._release_k
        self._gain += k * (desired - self._gain)

        # Rampa lineal dentro del bloque para evitar discontinuidades
        ramp = np.linspace(gain_prev, self._gain, len(samples), dtype=np.float32)
        return (samples * ramp).astype(np.float32)

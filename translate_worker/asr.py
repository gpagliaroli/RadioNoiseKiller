"""Wrapper de faster-whisper. Carga el modelo una vez; transcribe chunks de
audio PCM float32 mono que llegan ya decodificados (ver worker.py).

El array de audio tiene que venir YA a 16000 Hz (la tasa nativa de Whisper):
el remuestreo lo hace el cliente (src/translate_client.py), que ya tiene
scipy en su entorno — así este proceso no necesita esa dependencia extra
solo para resamplear."""
import numpy as np
from faster_whisper import WhisperModel

WHISPER_SAMPLE_RATE = 16000


class AsrEngine:
    def __init__(self, model_size: str = "tiny"):
        self.model_size = model_size
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray, sample_rate: int,
                    lang_src: str = "auto") -> tuple[str, float, list]:
        """audio: float32 mono. Devuelve (idioma_detectado, probabilidad,
        [dict(start, end, text), ...]). Lanza ValueError si sample_rate no es
        16000 — es responsabilidad del cliente remuestrear antes de mandar."""
        if sample_rate != WHISPER_SAMPLE_RATE:
            raise ValueError(
                f"audio a {sample_rate} Hz, se esperaba {WHISPER_SAMPLE_RATE} Hz "
                "(el cliente debe remuestrear antes de enviar)")
        # condition_on_previous_text=False: con audio ruidoso Whisper se
        # realimenta con su propio texto y repite la misma frase en bucle.
        # Cada chunk es independiente, así que no se pierde contexto útil.
        kwargs = dict(
            beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
            no_speech_threshold=0.6, compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            repetition_penalty=1.1, no_repeat_ngram_size=3,
        )
        if lang_src and lang_src != "auto":
            kwargs["language"] = lang_src
        segments, info = self.model.transcribe(audio, **kwargs)
        out = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
               for s in segments]
        return info.language, float(info.language_probability), out

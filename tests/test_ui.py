"""
Tests de UI (offscreen) — formaliza las verificaciones que antes se hacian
a mano en cada sesion. La UI es la categoria de regresion mas frecuente
(invariantes 5 y 8 del CLAUDE.md).

Cubre:
  - Estructura y orden de pestanas (incluida la pestana "Modulos" separada).
  - Que "Modulos activos" vive en su pestana, no en Principal.
  - Visibilidad de los botones de perfiles segun modo estatico/MCRA.
  - Gating de controles Avanzados por el estado de cada modulo
    (refresh_enabled_states + invariante 2: los sub-modulos requieren el cancelador).
  - Restauracion de checkboxes desde config (refresh_from_config, invariante 8).

NOTA: corre con QT_QPA_PLATFORM=offscreen (se fija abajo antes de importar Qt).
Los SliderRow deshabilitan sus HIJOS, no el contenedor: se testea con
`row._slider.isEnabled()`, no con `row.isEnabled()` (nota del CLAUDE.md, v1.6).

AISLAMIENTO: MainWindow lee/escribe settings.json, Presets/ y PerfilesRuido/
reales. Se redirigen a una carpeta temporal via RNK_DATA_DIR ANTES de construir
cualquier ventana — sin eso los tests pisan los presets de fábrica del usuario
(no regenerables) y se auto-envenenan entre corridas: un valor persistido igual
al que el test va a setear hace que QSlider.setValue() no emita valueChanged y
el test falla sin que haya bug (paso con post_filter_strength).
"""
import atexit
import os
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("RNK_NO_UPDATE_CHECK", "1")   # los tests nunca consultan GitHub
if not os.environ.get("RNK_DATA_DIR"):
    _tmp_data = tempfile.mkdtemp(prefix="rnk_test_ui_")
    os.environ["RNK_DATA_DIR"] = _tmp_data
    atexit.register(shutil.rmtree, _tmp_data, True)

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

_app = QApplication.instance() or QApplication([])

from config import AppConfig, read_ui_scale  # noqa: E402
from i18n import tr              # noqa: E402
from presets import PresetManager  # noqa: E402
from utils import presets_dir, settings_path  # noqa: E402
from ui.main_window import MainWindow, ui_scales_that_fit  # noqa: E402
from ui.slider_row import SliderRow  # noqa: E402

# Red de seguridad: si el redirect fallara, los tests escribirían sobre los datos
# reales del usuario. Mejor romper acá que borrar un preset de fábrica.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
assert not os.path.abspath(presets_dir()).startswith(_PROJECT_ROOT + os.sep), \
    f"Los tests apuntan a los Presets/ reales: {presets_dir()}"
assert not os.path.abspath(settings_path()).startswith(_PROJECT_ROOT + os.sep), \
    f"Los tests apuntan al settings.json real: {settings_path()}"

_PRESET_DE_PRUEBA = "___preset_de_prueba___"

# Preset semilla en la carpeta temporal (test_window_title_reflects_preset lo usa).
# El nombre es PROPIO del test a proposito: antes se llamaba como uno de fabrica
# y se leia como si el test dependiera de el, cuando en realidad lo crea aca.
PresetManager(presets_dir()).save(_PRESET_DE_PRUEBA, AppConfig())


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #

def _win() -> MainWindow:
    """Ventana mostrada (show() hace que isHidden() refleje el estado real)."""
    w = MainWindow()
    w.show()
    _app.processEvents()
    return w


def _combo_index(combo, data) -> int:
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            return i
    raise AssertionError(f"itemData {data!r} no esta en el combo")


def _set_combo(combo, data) -> None:
    combo.setCurrentIndex(_combo_index(combo, data))
    _app.processEvents()


# ---------------------------------------------------------------------- #
# 1. Estructura de pestanas                                               #
# ---------------------------------------------------------------------- #

def test_tab_order():
    """9 pestanas en orden fijo, con 'Modulos' en la 2da posicion."""
    w = _win()
    tabs = w._tabs
    expected = [
        tr("Principal"), tr("Módulos"), tr("Avanz. Audio"),
        tr("Avanz. Impulsos"), tr("Avanz. Cancelador"),
        tr("Espectro"), tr("EiBi"), tr("Presets"), tr("Traducción"),
    ]
    got = [tabs.tabText(i) for i in range(tabs.count())]
    assert got == expected, f"Orden de pestanas inesperado: {got}"
    print("Orden de pestanas (9, Modulos en pos 1)   OK")


def test_modules_group_moved_to_own_tab():
    """Los checkboxes de modulos viven en la pestana Modulos (idx 1),
    NO en Principal (idx 0). Guarda contra revertir el movimiento."""
    w = _win()
    principal = w._tabs.widget(0).findChildren(QCheckBox)
    modulos   = w._tabs.widget(1).findChildren(QCheckBox)
    assert w._chk_noise in modulos, "El cancelador no esta en la pestana Modulos"
    assert w._chk_noise not in principal, "El cancelador sigue en Principal"
    assert w._chk_exciter in modulos and w._chk_blanker in modulos
    print("Modulos activos en su pestana propia      OK")


# ---------------------------------------------------------------------- #
# 2. Botones de perfiles: visibles solo en modo estatico                  #
# ---------------------------------------------------------------------- #

def test_profile_buttons_visibility_by_mode():
    """Guardar perfil / Perfiles solo aplican en estatico; en MCRA se ocultan."""
    w = _win()
    _set_combo(w._combo_noise_mode, "static")
    assert not w._btn_save_profile.isHidden()
    assert not w._btn_load_profile.isHidden()

    _set_combo(w._combo_noise_mode, "mcra")
    assert w._btn_save_profile.isHidden(), "Guardar perfil visible en MCRA"
    assert w._btn_load_profile.isHidden(), "Perfiles visible en MCRA"

    _set_combo(w._combo_noise_mode, "static")
    assert not w._btn_save_profile.isHidden(), "Guardar perfil no reaparece"
    assert not w._btn_load_profile.isHidden(), "Perfiles no reaparece"
    print("Botones de perfiles ocultos en MCRA       OK")


# ---------------------------------------------------------------------- #
# 3. Gating de controles Avanzados por el estado de los modulos           #
# ---------------------------------------------------------------------- #

def test_post_filter_on_principal_autoenable():
    """El slider Post-Filtro (movido a Principal) auto-activa el post-filtro al
    pasar de 0 y lo apaga en 0, sincronizando el checkbox de Módulos."""
    w = _win()
    w._chk_post_filter.setChecked(False)
    w._slider_post.set_value(0.0)                # punto de partida conocido: setValue()
    _app.processEvents()                         # no emite si el valor ya coincide
    w._slider_post.set_value(4.0, emit=True)     # subir -> auto-activa
    _app.processEvents()
    assert w._config.dsp.post_filter_enabled, "post-filtro no se auto-activo al subir el slider"
    assert w._chk_post_filter.isChecked(), "checkbox de Modulos no se sincronizo"
    w._slider_post.set_value(0.0, emit=True)     # a 0 -> apaga
    _app.processEvents()
    assert not w._config.dsp.post_filter_enabled, "post-filtro no se apago en 0"
    print("Post-Filtro en Principal: auto-activar        OK")


def test_canceller_subcontrols_require_noise():
    """Invariante 2: los sub-modulos del cancelador no corren sin el cancelador.
    Con el cancelador OFF, sus sliders quedan deshabilitados aunque el
    sub-modulo este activo."""
    w = _win()
    can = w._adv_canceller_tab

    w._chk_noise.setChecked(True)
    w._chk_pitch_enhance.setChecked(True)
    _app.processEvents()
    assert can._s_pitch_strength._slider.isEnabled(), "pitch deberia estar habilitado"

    w._chk_noise.setChecked(False)   # apagar SOLO el cancelador
    _app.processEvents()
    assert not can._s_pitch_strength._slider.isEnabled(), \
        "pitch habilitado con cancelador OFF (invariante 2)"
    print("Sub-controles del cancelador gateados      OK")


def test_supresor_tiene_un_indicador_por_etapa():
    """Cada etapa del supresor tiene su indicador, y cada uno cuenta lo suyo.

    Antes habia UNO solo con la suma de los dos contadores, y ese numero lo
    domina la etapa mini (dispara por mini-frame; la de trama, una vez por
    bloque): medido sobre una grabacion real, con los umbrales por defecto la
    trama aportaba el 9,8% del total. Encima el indicador estaba arriba del
    slider de trama, que era justo el que menos reflejaba.
    """
    w = _win()
    tab = w._adv_impulse_tab
    bl = w._pipeline._blanker

    # Con los dos contadores en cero, los dos indicadores en reposo.
    w._pipeline.pop_blanker_hits()
    tab._update_stats()
    _app.processEvents()
    assert tab._lbl_blanker_hits.text() == "—"
    assert tab._lbl_blanker_hits_mini.text() == "—"

    # Solo trama: se enciende el de trama y el de micro NO.
    bl._hits_frame, bl._hits_mini = 7, 0
    tab._update_stats()
    _app.processEvents()
    assert "14" in tab._lbl_blanker_hits.text(), tab._lbl_blanker_hits.text()  # 7 por tick = 14/s
    assert tab._lbl_blanker_hits_mini.text() == "—", "el de micro contó disparos de trama"

    # Solo micro: al reves.
    bl._hits_frame, bl._hits_mini = 0, 9
    tab._update_stats()
    _app.processEvents()
    assert tab._lbl_blanker_hits.text() == "—", "el de trama contó disparos de micro"
    assert tab._lbl_blanker_hits_mini.text() != "—"

    # Un solo pop por tick: si se leyera una etapa por vez, la primera lectura
    # le vaciaria el contador a la otra y una de las dos nunca se encenderia.
    bl._hits_frame, bl._hits_mini = 3, 4
    tab._update_stats()
    _app.processEvents()
    assert tab._lbl_blanker_hits.text() != "—" and tab._lbl_blanker_hits_mini.text() != "—", \
        "una etapa se quedo sin conteo: el pop de la otra lo limpio"
    print("Supresor: un indicador por etapa            OK")


def test_umbral_de_trama_llega_a_la_zona_util():
    """El umbral de trama del supresor tiene que llegar a 2-6 y con paso fino.

    Hasta la v2.3 el slider iba de 5 a 100: medido, esta etapa deja de disparar
    arriba de ~20 (el 80% del recorrido no hacia nada) y su zona util contra las
    rafagas de nivel del fading es 3-6, o sea que arrancaba POR DEBAJO del minimo
    y no se podia llegar desde la UI. El usuario terminaba bajando el umbral MICRO
    para compensar, que rinde menos y opaca la voz (con micro en 4 la distorsion
    sobre voz limpia es -8,7 dB, peor que el bug que arreglo la v2.2).
    """
    w = _win()
    row = w._adv_impulse_tab._s_blanker_frame
    bl = w._pipeline._blanker

    assert row._min <= 3.0, "el minimo no llega a la zona util (3-6)"
    assert row._max <= 30.0, "el maximo sigue en una zona donde la etapa no dispara"
    # Ningun preset de fabrica ni el settings guardan mas de 30: si el maximo
    # bajara de ahi, cargarlos los recortaria y marcarian (modificado).

    # Paso fino: dos posiciones consecutivas de la zona util tienen que existir.
    row.set_value(4.0, emit=True)
    _app.processEvents()
    assert abs(bl._frame_thr - 4.0) < 0.01, bl._frame_thr
    row.set_value(4.25, emit=True)
    _app.processEvents()
    assert abs(bl._frame_thr - 4.25) < 0.01, "el paso no permite afinar en la zona util"
    assert abs(w._config.dsp.blanker_frame - 4.25) < 0.01

    # Los extremos llegan enteros al DSP (invariante 1: clamp >= rango del slider).
    for v in (row._min, row._max):
        row.set_value(v, emit=True)
        _app.processEvents()
        assert abs(bl._frame_thr - v) < 0.01, "el clamp del DSP recorta el slider (%g)" % v
    print("Umbral de trama: alcanza la zona util       OK")


def test_sliders_de_lambda_d_solo_en_adaptativo():
    """Los tres sliders que tocan lambda_d quedan grises en Perfil estatico.

    Verificado midiendo sobre el profiler: en estatico la salida es identica bit a
    bit con cualquier valor de los tres, porque el piso sale del perfil aprendido y
    es fijo. Antes quedaban habilitados y sin efecto, que es peor que estar grises.
    El refuerzo en agudos NO entra: multiplica el piso venga de donde venga."""
    w = _win()
    can = w._adv_canceller_tab
    w._chk_noise.setChecked(True)
    _app.processEvents()

    solo_mcra = (can._s_mcra_window, can._s_noise_freeze, can._s_noise_fall)

    _set_combo(w._combo_noise_mode, "mcra")
    _app.processEvents()
    for s in solo_mcra:
        assert s._slider.isEnabled(), "deshabilitado en Adaptativo, donde SI actua"
    assert can._s_hf_boost._slider.isEnabled()

    _set_combo(w._combo_noise_mode, "static")
    _app.processEvents()
    for s in solo_mcra:
        assert not s._slider.isEnabled(), \
            "habilitado en estatico, donde no hace nada"
    # El control que si funciona en los dos modos no debe caer en la misma bolsa.
    assert can._s_hf_boost._slider.isEnabled(), \
        "refuerzo en agudos deshabilitado en estatico, donde SI actua"

    # Y el gating tiene que sobrevivir a apagar/prender el cancelador en estatico.
    w._chk_noise.setChecked(False)
    _app.processEvents()
    w._chk_noise.setChecked(True)
    _app.processEvents()
    for s in solo_mcra:
        assert not s._slider.isEnabled(), "reaparecio habilitado tras togglear el cancelador"
    _set_combo(w._combo_noise_mode, "mcra")
    _app.processEvents()
    print("Sliders de lambda_d: grises en estatico    OK")


def test_bass_and_character_controls():
    """Recuperar graves: modulo propio (no depende del cancelador — su f0 sale de
    la autocorrelacion, que corre siempre) y su slider se gatea con el checkbox.
    El Caracter del excitador se gatea con el excitador."""
    w = _win()
    aud = w._adv_audio_tab

    w._chk_bass.setChecked(False)
    _app.processEvents()
    assert not aud._s_bass._slider.isEnabled(), "el slider de graves deberia estar apagado"

    w._chk_bass.setChecked(True)
    _app.processEvents()
    assert aud._s_bass._slider.isEnabled(), "el slider de graves no se habilito"
    assert w._config.dsp.bass_enabled, "el checkbox no llego a la config"

    # No depende del cancelador (a diferencia de los sub-modulos, invariante 2)
    w._chk_noise.setChecked(False)
    _app.processEvents()
    assert aud._s_bass._slider.isEnabled(), "los graves no deberian depender del cancelador"
    w._chk_noise.setChecked(True)

    w._chk_exciter.setChecked(False)
    _app.processEvents()
    assert not aud._s_exciter_char._slider.isEnabled(), "el caracter deberia seguir al excitador"
    w._chk_exciter.setChecked(True)
    _app.processEvents()
    assert aud._s_exciter_char._slider.isEnabled(), "el caracter no se habilito"

    aud._s_exciter_char.set_value(0.6, emit=True)
    _app.processEvents()
    assert abs(w._config.dsp.exciter_character - 0.6) < 1e-6, "el caracter no llego a la config"
    print("Graves y caracter: gating y config          OK")


def test_agc_noise_ceiling_controls():
    """Techo de ruido del AGC: vive en el grupo Control de la pestaña Principal
    (es un ajuste del AGC y se calibra escuchando, junto al combo que lo activa),
    NO en Avanzada Audio. El slider sigue al checkbox y ambos llegan a config."""
    w = _win()

    principal = w._tabs.widget(0)
    assert w._chk_agc_ceiling in principal.findChildren(QCheckBox), \
        "el techo de ruido no esta en la pestaña Principal"

    w._chk_agc_ceiling.setChecked(False)
    _app.processEvents()
    assert not w._s_agc_ceiling._slider.isEnabled(), "el slider deberia estar apagado"

    w._chk_agc_ceiling.setChecked(True)
    _app.processEvents()
    assert w._s_agc_ceiling._slider.isEnabled(), "el slider no se habilito"
    assert w._config.dsp.agc_noise_ceiling_enabled, "el checkbox no llego a la config"

    w._s_agc_ceiling.set_value(-50.0, emit=True)
    _app.processEvents()
    assert abs(w._config.dsp.agc_noise_ceiling_db + 50.0) < 1e-6, "el umbral no llego a la config"
    print("Techo de ruido del AGC: controles           OK")


def test_voice_leveler_requires_noise():
    """El nivelador de voz vive en Avanzada Audio pero su VAD requiere el
    cancelador (invariante 2)."""
    w = _win()
    aud = w._adv_audio_tab

    w._chk_noise.setChecked(True)
    w._chk_voice_leveler.setChecked(True)
    _app.processEvents()
    assert aud._s_leveler_max._slider.isEnabled(), "nivelador deberia habilitarse"

    w._chk_noise.setChecked(False)
    _app.processEvents()
    assert not aud._s_leveler_max._slider.isEnabled(), \
        "nivelador habilitado sin cancelador (invariante 2)"
    print("Nivelador de voz requiere cancelador       OK")


def test_leveler_continuous_checkbox():
    """La casilla 'Nivelar en continuo' invierte el gate por voz del nivelador
    (marcada = sin gate = musica) y se gatea con el cancelador + nivelador.
    Vive en el grupo Control de la pestaña Principal (hay que tenerla a la vista
    para elegir voz/musica), no en Avanzada Audio."""
    w = _win()
    assert w._chk_leveler_continuous in w._tabs.widget(0).findChildren(QCheckBox),         "la casilla no esta en la pestaña Principal"

    # Gateada por el cancelador + nivelador (invariante 2)
    w._chk_noise.setChecked(True)
    w._chk_voice_leveler.setChecked(True)
    _app.processEvents()
    assert w._chk_leveler_continuous.isEnabled(), "casilla deberia habilitarse"

    # Estado inicial conocido (settings.json de dev puede tener gate=False → casilla
    # ya marcada); sin esto setChecked(True) seria no-op y no dispararia la señal.
    w._chk_leveler_continuous.blockSignals(True)
    w._chk_leveler_continuous.setChecked(False)
    w._chk_leveler_continuous.blockSignals(False)

    calls = []
    orig = w._pipeline.set_voice_leveler_gate_voice
    w._pipeline.set_voice_leveler_gate_voice = lambda g: calls.append(g)
    try:
        w._chk_leveler_continuous.setChecked(True)   # continuo → SIN gate de voz
        assert calls[-1] is False, "continuo marcado deberia desactivar el gate (gate=False)"
        w._chk_leveler_continuous.setChecked(False)  # gateado por voz
        assert calls[-1] is True, "continuo desmarcado deberia activar el gate (gate=True)"
    finally:
        w._pipeline.set_voice_leveler_gate_voice = orig

    w._chk_noise.setChecked(False)
    _app.processEvents()
    assert not w._chk_leveler_continuous.isEnabled(), \
        "casilla habilitada sin cancelador (invariante 2)"
    print("Nivelador: casilla continuo + gating         OK")


def test_bandpass_preset_combo():
    """El combo Pasabanda aplica los limites, y editarlos a mano lo pasa a
    Personalizado (si no, el combo mentiria sobre lo que esta sonando)."""
    from config import BANDPASS_PRESETS, BANDPASS_CUSTOM
    w = _win()
    aud = w._adv_audio_tab
    w._config.dsp.bandpass_pre_enabled = True

    _set_combo(w._combo_bandpass, "AM 6 kHz")
    assert tuple(w._config.dsp.bandpass_limits) == BANDPASS_PRESETS["AM 6 kHz"]
    # value() del SliderRow, no _slider.value(): el QSlider guarda el valor
    # ESCALADO a entero (paso de 10 Hz), no los Hz.
    assert aud._s_bp_hi.value() == BANDPASS_PRESETS["AM 6 kHz"][1],         "los sliders de Avanzada no siguieron al combo"

    _set_combo(w._combo_bandpass, "SSB angosto")
    assert tuple(w._config.dsp.bandpass_limits) == BANDPASS_PRESETS["SSB angosto"]

    # Editar a mano -> Personalizado, y el combo lo refleja
    aud._s_bp_hi.set_value(2550, emit=True)
    _app.processEvents()
    assert w._config.dsp.bandpass_preset == BANDPASS_CUSTOM,         "editar los limites no paso el preset a Personalizado"
    assert w._combo_bandpass.currentData() == BANDPASS_CUSTOM,         "el combo no siguio al cambio manual"
    print("Combo Pasabanda: aplica y detecta manual   OK")


def test_bandpass_preset_ambiguo_no_salta():
    """Dos entradas comparten Hz (SSB ancho / AM 3 kHz): elegir la segunda no
    debe saltar sola a la primera al re-derivar el nombre desde los limites."""
    from config import BANDPASS_PRESETS
    assert BANDPASS_PRESETS["SSB ancho"] == BANDPASS_PRESETS["AM 3 kHz"],         "el test asume que estos dos comparten limites"
    w = _win()
    _set_combo(w._combo_bandpass, "AM 3 kHz")
    assert w._config.dsp.bandpass_preset == "AM 3 kHz", w._config.dsp.bandpass_preset
    assert w._combo_bandpass.currentData() == "AM 3 kHz"

    # Y tiene que sobrevivir a apply_config, que es el camino de "cargar preset".
    # El guard de apply_config era INERTE: en la UI `config` y el config del
    # pipeline son el MISMO objeto, asi que set_bandpass_limits ya habia pisado el
    # nombre y la linea de restauracion se asignaba el valor corrupto a si misma.
    # Sintoma: "(modificado)" espurio permanente en un preset guardado con
    # cualquiera de los dos anchos que comparten Hz.
    w._pipeline.apply_config(w._config)
    assert w._config.dsp.bandpass_preset == "AM 3 kHz",         "apply_config re-derivo el nombre: %s" % w._config.dsp.bandpass_preset

    # Un nombre que NO corresponde a los Hz vigentes si debe re-derivarse: el combo
    # no puede mentir sobre lo que suena.
    w._config.dsp.bandpass_preset = "AM 8 kHz"
    w._pipeline.apply_config(w._config)
    assert w._config.dsp.bandpass_preset in ("SSB ancho", "AM 3 kHz"),         "un nombre incoherente con los Hz sobrevivio: %s" % w._config.dsp.bandpass_preset
    _set_combo(w._combo_bandpass, "AM 3 kHz")
    print("Combo Pasabanda: no salta entre iguales    OK")


def test_bandpass_out_requires_post_and_independent():
    """Los sliders de salida independiente requieren bandpass post + la casilla."""
    w = _win()
    aud = w._adv_audio_tab

    w._chk_bandpass_post.setChecked(True)
    aud._chk_bp_out.setChecked(True)
    _app.processEvents()
    assert aud._s_out_lo._slider.isEnabled(), "salida independiente deberia habilitarse"

    aud._chk_bp_out.setChecked(False)
    _app.processEvents()
    assert not aud._s_out_lo._slider.isEnabled(),         "salida independiente habilitada con la casilla OFF"

    aud._chk_bp_out.setChecked(True)
    w._chk_bandpass_post.setChecked(False)
    _app.processEvents()
    assert not aud._s_out_lo._slider.isEnabled(),         "salida independiente habilitada con bandpass post OFF"
    print("Bandpass salida independiente gateado      OK")


# ---------------------------------------------------------------------- #
# 4. Restauracion de checkboxes desde config (invariante 8)               #
# ---------------------------------------------------------------------- #

def test_refresh_from_config_restores_checkboxes():
    """refresh_from_config debe reflejar en los checkboxes lo que hay en config."""
    w = _win()
    dsp = w._config.dsp
    # Estado conocido, distinto en varios flags
    dsp.noise_enabled     = True
    dsp.exciter_enabled   = False
    dsp.gate_enabled      = True
    dsp.presence_enabled  = False
    dsp.anf_enabled       = True
    w.refresh_from_config()
    _app.processEvents()

    assert w._chk_noise.isChecked() is True
    assert w._chk_exciter.isChecked() is False
    assert w._chk_gate.isChecked() is True
    assert w._chk_presence.isChecked() is False
    assert w._chk_anf.isChecked() is True
    print("refresh_from_config restaura checkboxes    OK")


# ---------------------------------------------------------------------- #
# 5. Titulo de la ventana refleja el preset activo                        #
# ---------------------------------------------------------------------- #

def test_window_title_reflects_preset():
    """El titulo muestra el preset activo y '(modificado)' si el config difiere."""
    w = _win()

    w._config.last_preset = ""
    w._update_window_title()
    assert "RadioNoiseKiller" in w.windowTitle()

    # Preset activo sin modificar: cargar sus valores en config
    name = _PRESET_DE_PRUEBA
    if w._preset_manager.exists(name):
        w._preset_manager.load_into(name, w._config)
        w._config.last_preset = name
        w._update_window_title()
        assert name in w.windowTitle(), "el preset no aparece en el titulo"
        assert tr("{name}  (modificado)").format(name=name) not in w.windowTitle()

        # Modificar un valor -> '(modificado)'
        w._config.dsp.noise_alpha = 0.99
        w._update_window_title()
        assert tr("{name}  (modificado)").format(name=name) in w.windowTitle(), \
            "no aparece (modificado) tras editar"
    print("Titulo refleja preset + (modificado)      OK")


def test_overwrite_clears_modified_in_title():
    """Tras 'Sobrescribir seleccionado', el '(modificado)' del título debe irse:
    la config ya coincide con el preset guardado (bug: _set_active no emitía
    state_changed si el nombre activo no cambiaba)."""
    w = _win()
    pt = w._presets_tab
    tmp = "___test_overwrite_tmp___"
    modificado = tr("{name}  (modificado)").format(name=tmp)
    try:
        # Crear un preset temporal a partir de la config actual y activarlo
        w._preset_manager.save(tmp, w._config)
        pt._refresh_list()
        pt._select_by_name(tmp)
        pt._on_load()
        _app.processEvents()

        # Modificar la config -> el título muestra (modificado)
        w._config.dsp.noise_alpha = 0.123
        w._update_window_title()
        assert modificado in w.windowTitle(), "no aparece (modificado) tras editar"

        # Sobrescribir -> debe limpiarse
        pt._select_by_name(tmp)
        pt._on_overwrite()
        _app.processEvents()
        assert modificado not in w.windowTitle(), \
            "el título sigue '(modificado)' tras sobrescribir"
        assert tmp in w.windowTitle()
        print("Sobrescribir limpia (modificado) del título  OK")
    finally:
        w._preset_manager.delete(tmp)


def test_export_import_preset_buttons():
    """Exportar escribe un .json suelto con el preset elegido; importarlo de
    vuelta (con otro nombre, sin colisión) lo deja disponible en la lista."""
    import json
    import ui.presets_tab as pt_mod

    w = _win()
    pt = w._presets_tab
    origen = "___test_export_origen___"
    importado = "___test_export_importado___"
    tmp_json = os.path.join(tempfile.gettempdir(), "___rnk_test_export___.json")
    orig_save, orig_open = pt_mod.QFileDialog.getSaveFileName, pt_mod.QFileDialog.getOpenFileName
    try:
        w._preset_manager.save(origen, w._config)
        pt._refresh_list()
        pt._select_by_name(origen)

        pt_mod.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (tmp_json, ""))
        pt._on_export()
        assert os.path.exists(tmp_json), "export_to no escribio el archivo"
        with open(tmp_json, encoding="utf-8") as f:
            data = json.load(f)
        assert data["name"] == origen

        # Renombrar el nombre dentro del json antes de reimportar, para que no
        # colisione con el original y testear el camino "sin colision".
        data["name"] = importado
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(data, f)

        pt_mod.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (tmp_json, ""))
        pt._on_import()
        _app.processEvents()
        assert importado in w._preset_manager.list_names(), \
            "el preset importado no aparece en la lista"
        print("Exportar/importar preset (sin colision)     OK")
    finally:
        pt_mod.QFileDialog.getSaveFileName = orig_save
        pt_mod.QFileDialog.getOpenFileName = orig_open
        w._preset_manager.delete(origen)
        w._preset_manager.delete(importado)
        if os.path.exists(tmp_json):
            os.remove(tmp_json)


def test_import_preset_name_collision_overwrite():
    """Importar un preset con un nombre que ya existe pregunta, y elegir
    'Sobrescribir' reemplaza el preset existente con los datos importados."""
    import json
    from PySide6.QtWidgets import QMessageBox
    import ui.presets_tab as pt_mod

    w = _win()
    pt = w._presets_tab
    nombre = "___test_import_colision___"
    tmp_json = os.path.join(tempfile.gettempdir(), "___rnk_test_import_colision___.json")
    orig_open = pt_mod.QFileDialog.getOpenFileName
    orig_exec = QMessageBox.exec
    try:
        app_viejo = AppConfig()
        app_viejo.dsp.noise_alpha = 0.11
        w._preset_manager.save(nombre, app_viejo)

        app_nuevo = AppConfig()
        app_nuevo.dsp.noise_alpha = 0.99
        from presets import PresetManager as PM
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(PM._capture(nombre, app_nuevo), f)

        pt_mod.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (tmp_json, ""))

        def _exec_click_overwrite(self):
            for b in self.buttons():
                if tr("Sobrescribir") in b.text():
                    b.click()
                    return 0
            raise AssertionError("no se encontro el boton Sobrescribir")
        QMessageBox.exec = _exec_click_overwrite

        pt._on_import()
        _app.processEvents()
        assert w._preset_manager.snapshot(nombre)["dsp"]["noise_alpha"] == 0.99, \
            "sobrescribir no aplico los datos importados"
        print("Importar con colision -> Sobrescribir       OK")
    finally:
        pt_mod.QFileDialog.getOpenFileName = orig_open
        QMessageBox.exec = orig_exec
        w._preset_manager.delete(nombre)
        if os.path.exists(tmp_json):
            os.remove(tmp_json)


def test_advanced_change_marks_modified():
    """Mover un slider de una pestaña Avanzada debe marcar el preset como
    '(modificado)' (esos sliders conectan directo al pipeline; sin la señal
    'changed' → _schedule_save el título nunca se actualizaba)."""
    w = _win()
    pt = w._presets_tab
    tmp = "___test_adv_mod___"
    modificado = tr("{name}  (modificado)").format(name=tmp)
    try:
        w._preset_manager.save(tmp, w._config)
        pt._refresh_list()
        pt._select_by_name(tmp)
        pt._on_load()
        _app.processEvents()
        assert modificado not in w.windowTitle(), "tras cargar no debería estar modificado"

        # Cambiar un slider de Avanzada Impulsos (ANF) por su widget
        cur = w._config.dsp.anf_depth
        w._adv_impulse_tab._s_anf_depth.set_value(0.95 if cur < 0.9 else 0.1, emit=True)
        _app.processEvents()
        assert modificado in w.windowTitle(), \
            "un cambio en Avanzadas no marcó (modificado)"

        # Recargar el preset debe limpiar (sin falsos positivos por el reload)
        pt._on_load()
        _app.processEvents()
        assert modificado not in w.windowTitle(), "reload no limpió (modificado)"
        print("Cambio en Avanzadas marca (modificado)     OK")
    finally:
        w._preset_manager.delete(tmp)


def test_waterfall_toggle_and_source():
    """La cascada: casilla la muestra/oculta y habilita el selector; el cambio de
    fuente persiste; empujar filas headless no crashea."""
    import numpy as np
    w = _win()

    # El splitter de la pestaña Espectro tiene espectro + cascada
    assert w._spectrum_splitter.count() == 2, "el splitter deberia tener 2 widgets"
    wf = w._waterfall_widget

    # La casilla refleja la config cargada (no asumimos un default persistido:
    # settings.json de dev puede tener la cascada apagada de una sesion anterior)
    assert w._chk_waterfall.isChecked() == w._config.window.spectrum_show_waterfall
    assert w._combo_waterfall_src.isEnabled() == w._chk_waterfall.isChecked()

    # Encender: combo habilitado
    w._chk_waterfall.setChecked(True)
    _app.processEvents()
    assert w._combo_waterfall_src.isEnabled()

    # Apagar: oculta el widget y deshabilita el combo, persiste en config
    w._chk_waterfall.setChecked(False)
    _app.processEvents()
    assert not w._combo_waterfall_src.isEnabled(), "combo habilitado con cascada off"
    assert w._config.window.spectrum_show_waterfall is False

    # Encender de nuevo y cambiar la fuente -> persiste
    w._chk_waterfall.setChecked(True)
    _app.processEvents()
    _set_combo(w._combo_waterfall_src, "output")
    assert w._config.window.waterfall_source == "output"

    # Empujar filas dB no debe crashear (ni activo ni activo)
    wf.start()
    wf.set_max_freq_hz(6000)
    db = np.linspace(-80, -10, wf._n_bins).astype(np.float32)
    for _ in range(30):
        wf.push_row(db)
    wf.resize(600, 200)
    wf.repaint()

    # Profundidad de historia: el combo la cambia y persiste. El buffer NO se
    # redimensiona (esta dimensionado para el maximo): cambiarla es un zoom, no
    # descarta lo capturado.
    buffer_filas = wf._rows
    for secs in (15, 120, 30):
        _set_combo(w._combo_waterfall_hist, secs)
        assert w._config.window.waterfall_history_sec == secs, "no persistio la profundidad"
        assert wf._visible_rows() <= wf._rows
        wf.repaint()
    assert wf._rows == buffer_filas, "el buffer no deberia redimensionarse"
    assert wf._visible_rows() < buffer_filas, "a 30 s deberia dibujar menos que el buffer"
    assert w._combo_waterfall_hist.isEnabled() == w._chk_waterfall.isChecked()

    # Marcadores de heterodino: aceptar tonos, ninguno, y repintar sin crashear
    for tonos in (np.array([1500.0, 3200.0], dtype=np.float32), None):
        wf.set_tone_freqs(tonos)
        wf.repaint()
    print("Cascada: toggle + fuente + profundidad + marcadores  OK")


def test_alternate_rows_dark_on_linux_style():
    """Las filas alternas de Presets y EiBi no pueden salir blancas. Con el estilo
    de Linux (Fusion) Qt pinta el AlternateBase del tema del sistema (#f7f7f7)
    si la hoja de estilo no lo define, y el texto claro se vuelve ilegible —
    reportado en la Raspberry Pi. En Windows no se veía."""
    from PySide6.QtWidgets import QStyleFactory, QTableWidgetItem

    w = _win()
    try:
        fusion = QStyleFactory.create("Fusion")
        lst = w._presets_tab._list
        lst.clear()
        lst.addItems(["uno", "dos", "tres", "cuatro"])
        tabla = w._eibi_tab._table
        tabla.setRowCount(4)
        for r in range(4):
            tabla.setItem(r, 0, QTableWidgetItem(str(r)))
        for vista in (lst, tabla):
            vista.setStyle(fusion)
            vista.resize(300, 200)
            vista.show()
            _app.processEvents()
            img = vista.viewport().grab().toImage()
            h = vista.sizeHintForRow(0)
            for fila in (1, 3):
                c = img.pixelColor(img.width() - 5, fila * h + h // 2)
                assert c.lightnessF() < 0.35, \
                    f"{type(vista).__name__}: fila alterna {fila} clara ({c.name()})"
            vista.hide()
    finally:
        w.close()
    print("Filas alternas oscuras con el estilo de Linux     OK")


def test_waterfall_rgb_incremental():
    """La cascada colorea cada fila al empujarla (y todo el ring sólo al cambiar
    la escala). Tiene que pintar EXACTAMENTE lo mismo que el método viejo, que
    recoloreaba todo lo visible en cada repintado."""
    import numpy as np
    from ui.waterfall_widget import WaterfallWidget

    wf = WaterfallWidget()

    def viejo():
        mb, nvis = wf._max_bin, wf._visible_rows()
        order = (wf._cursor - np.arange(nvis)) % wf._rows
        lo, span, lut = wf._scale()
        frac = np.clip((wf._ring[order, :mb] - lo) / span, 0.0, 1.0)
        return lut[(frac * 255.0).astype(np.uint8)]

    def nuevo():
        order = (wf._cursor - np.arange(wf._visible_rows())) % wf._rows
        return wf._rgb_ring[order, :wf._max_bin]

    rng = np.random.default_rng(3)
    assert np.array_equal(viejo(), nuevo()), "ring vacío al construir"
    wf.start()
    for paso, accion in enumerate((lambda: None,
                                   lambda: wf.set_db_max(-30),
                                   lambda: wf.set_max_freq_hz(4000),
                                   lambda: wf.set_history_sec(10),
                                   lambda: wf.set_diff_mode(True),
                                   lambda: wf.set_db_max(-10),   # no toca la escala diff
                                   lambda: wf.set_diff_mode(False),
                                   lambda: wf.clear())):
        accion()
        for _ in range(40):
            wf.push_row(rng.uniform(-100, 20, 1025 - paso).astype(np.float32))
        assert np.array_equal(viejo(), nuevo()), f"difiere del método viejo en el paso {paso}"
    wf.stop()
    assert np.array_equal(viejo(), nuevo()), "ring vacío al detener"
    print("Cascada: coloreo incremental = método viejo  OK")


def test_waterfall_diff_mode():
    """Modo Diferencia de la cascada: el combo lo selecciona y persiste, la fila
    empujada es entrada−salida en dB (sin recortar a −80, que taparia la
    supresion profunda), la escala es fija (el slider Max Y no la toca) y el
    signo se pinta con mitades distintas de la LUT divergente."""
    import numpy as np
    from ui.spectrum_widget import SpectrumWidget
    from PySide6.QtGui import QColor

    w = _win()
    wf = w._waterfall_widget
    w._chk_waterfall.setChecked(True)
    _app.processEvents()

    # --- combo -> config + widgets ---------------------------------------
    _set_combo(w._combo_waterfall_src, "diff")
    assert w._config.window.waterfall_source == "diff", "no persistio la fuente diff"
    assert wf._diff_mode is True, "el widget no entro en modo diferencia"
    assert w._spectrum_widget._waterfall_source == "diff"

    # El buffer vacio vale 0 (= sin cambio). Con el relleno de nivel (−80) la
    # pantalla vacia caeria en el extremo "amplificado" y se pintaria de magenta.
    assert wf._empty_value == 0.0
    assert float(wf._ring.max()) == 0.0 and float(wf._ring.min()) == 0.0

    # --- escala fija, independiente del slider Max Y ----------------------
    lo0, span0, lut0 = wf._scale()
    wf.set_db_max(-40)
    lo1, span1, _ = wf._scale()
    assert (lo0, span0) == (lo1, span1), "Max Y movio la escala de diferencia"
    assert (lo0, span0) == (-wf.DIFF_SPAN, 2 * wf.DIFF_SPAN)
    assert lut0 is wf._LUT_DIFF, "modo diferencia usando la LUT de nivel"
    # y en modo nivel vuelve a depender de Max Y
    wf.set_diff_mode(False)
    assert wf._scale()[2] is wf._LUT
    wf.set_diff_mode(True)

    # --- la fila empujada es la reduccion real, sin recorte a −80 ---------
    class _FakeWf:
        def __init__(self):
            self.rows = []

        def push_row(self, row):
            self.rows.append(np.asarray(row))

    sp = SpectrumWidget()
    sp.show()
    _app.processEvents()
    fake = _FakeWf()
    sp.waterfall = fake
    sp.set_waterfall_enabled(True)
    sp.set_waterfall_source("diff")

    n = SpectrumWidget.FFT_SIZE
    t = np.arange(n, dtype=np.float32) / SpectrumWidget.SAMPLE_RATE
    tono = np.sin(2 * np.pi * 1000.0 * t).astype(np.float32)
    # Entrada ~−32 dBFS; salida 80 dB mas abajo (supresion profunda: la salida
    # queda MUY por debajo del piso de −80 dB de las curvas del espectro).
    sp.pre_frames.append(0.05 * tono)
    sp.post_frames.append(0.05e-4 * tono)
    sp._tick()
    assert fake.rows, "_tick no empujo ninguna fila en modo diferencia"
    fila = fake.rows[-1]
    pico = int(round(1000.0 / sp._freq_per_bin))
    assert 70.0 < float(fila[pico]) < 90.0, (
        f"la diferencia en el bin de 1 kHz deberia ser ~80 dB, dio {fila[pico]:.1f} "
        "(si da ~48 es que se esta recortando a −80 dB antes de restar)")

    # Con las dos fuentes iguales la diferencia es 0 (nada que mostrar)
    sp.pre_frames.clear(); sp.post_frames.clear()
    sp.pre_frames.append(0.05 * tono)
    sp.post_frames.append(0.05 * tono)
    sp._tick()
    assert abs(float(fake.rows[-1][pico])) < 0.5, "sin cambio deberia dar ~0 dB"

    # Falta una de las dos fuentes -> no se empuja fila (mejor hueco que mentira)
    antes = len(fake.rows)
    sp.post_frames.clear()
    sp._tick()
    assert len(fake.rows) == antes, "empujo fila con una sola fuente disponible"

    # --- el signo se pinta con mitades distintas de la LUT ----------------
    def _colores(valor):
        wf.set_diff_mode(False); wf.set_diff_mode(True)   # limpia el buffer
        wf.start()
        wf.set_max_freq_hz(6000)
        fila = np.full(wf._n_bins, valor, dtype=np.float32)
        # Llenar TODA la profundidad visible: con menos filas la parte de abajo
        # queda con el relleno vacio y el pixel del centro no dice nada.
        for _ in range(wf._visible_rows()):
            wf.push_row(fila)
        wf.resize(600, 200)
        pm = wf.grab()
        img = pm.toImage()
        # centro del area de dibujo (lejos de margenes, ejes y colorbar)
        return QColor(img.pixel(pm.width() // 2, pm.height() // 2))

    quitado = _colores(+25.0)    # se quito señal -> extremo calido
    puesto  = _colores(-25.0)    # se amplifico   -> extremo violeta
    neutro  = _colores(0.0)      # sin cambio     -> fondo
    assert quitado.red() > 150 and quitado.blue() < 80, (
        f"reduccion fuerte deberia pintar calido, dio {quitado.getRgb()}")
    assert puesto.blue() > 100 and puesto.green() < 80, (
        f"amplificacion deberia pintar violeta, dio {puesto.getRgb()}")
    assert neutro.red() < 40 and neutro.green() < 40, (
        f"sin cambio deberia quedar en el fondo, dio {neutro.getRgb()}")

    # dejar la cascada como estaba para no ensuciar otros tests
    _set_combo(w._combo_waterfall_src, "input")
    assert wf._diff_mode is False, "no volvio a modo nivel"
    print("Cascada: modo Diferencia (escala, resta y colores)   OK")


def test_incompatible_devices_disable_activate():
    """Aviso proactivo -9993: con entrada/salida en APIs distintas, ACTIVAR
    queda deshabilitado y los combos marcados; al volver a ser compatibles,
    ACTIVAR se re-habilita y el borde se limpia. Se fuerza el mismatch
    monkeypatcheando duplex_hostapi_mismatch (sin depender del hardware)."""
    import ui.main_window as mw

    w = _win()
    # Estado base: la ventana ya construida debe permitir ACTIVAR
    # (el hardware del runner, si hay, es compatible o no hay devices).
    orig = mw.duplex_hostapi_mismatch
    try:
        # Forzar combinación incompatible
        mw.duplex_hostapi_mismatch = lambda i, o: ("Windows WASAPI", "Windows WDM-KS")
        w._check_device_compatibility()
        assert not w._btn_start.isEnabled(), "ACTIVAR habilitado con APIs incompatibles"
        assert w._combo_in.styleSheet(), "combo de entrada sin marca de aviso"
        assert w._combo_out.styleSheet(), "combo de salida sin marca de aviso"
        assert w._devices_incompatible is True

        # Volver a compatible -> re-habilita y limpia
        mw.duplex_hostapi_mismatch = lambda i, o: None
        w._check_device_compatibility()
        assert w._btn_start.isEnabled(), "ACTIVAR sigue deshabilitado tras compatibilizar"
        assert not w._combo_in.styleSheet(), "marca de entrada no se limpio"
        assert not w._combo_out.styleSheet(), "marca de salida no se limpio"
        assert w._devices_incompatible is False
    finally:
        mw.duplex_hostapi_mismatch = orig
    print("Aviso proactivo -9993: ACTIVAR gateado         OK")


def test_loaded_profile_name_label():
    """El nombre del perfil nombrado cargado se muestra debajo de los botones;
    se oculta al Aprender/Borrar (perfil ad-hoc), sin perfil, o en modo MCRA.
    Se fuerza 'hay perfil' monkeypatcheando la property del pipeline (sin hardware)."""
    w = _win()
    _set_combo(w._combo_noise_mode, "static")

    pipe_cls = type(w._pipeline)
    orig_has = pipe_cls.noise_has_profile
    pipe_cls.noise_has_profile = property(lambda self: True)
    try:
        # Perfil nombrado cargado -> el label aparece con el nombre
        w._active_noise_profile_name = "40m casa"
        w._refresh_noise_profile_ui()
        assert not w._label_profile_name.isHidden(), "label del nombre no aparece con perfil cargado"
        assert "40m casa" in w._label_profile_name.text(), "el label no muestra el nombre"

        # Perfil ad-hoc (aprendido a mano) -> nombre None -> label oculto
        w._active_noise_profile_name = None
        w._refresh_noise_profile_ui()
        assert w._label_profile_name.isHidden(), "label visible con perfil aprendido a mano"

        # Con nombre pero en MCRA -> oculto (no aplica el modo)
        w._active_noise_profile_name = "40m casa"
        _set_combo(w._combo_noise_mode, "mcra")
        assert w._label_profile_name.isHidden(), "label del nombre visible en MCRA"
    finally:
        pipe_cls.noise_has_profile = orig_has
    print("Nombre del perfil cargado en la UI         OK")


def test_bypass_es_boton_junto_al_mute():
    """Bypass paso de casilla (grupo Control) a boton en la fila de Grabar/Mute.

    Los tres son acciones de escucha que se aprietan y se sueltan mientras se
    opera, no ajustes que se dejan puestos. A diferencia de Grabar y Mute, Bypass
    NO se deshabilita sin proceso: dejarlo preparado antes de activar es util, y
    la ganancia de salida se recuerda por modo, asi que se calibra cada lado
    aparte.
    """
    from PySide6.QtWidgets import QPushButton

    w = _win()
    b = w._btn_bypass
    assert isinstance(b, QPushButton) and b.isCheckable(), "Bypass deberia ser un boton"
    assert b.parent() is w._btn_mute.parent(), "Bypass no quedo en la fila del Mute"
    assert b.isEnabled(), "Bypass no debe requerir el proceso activo"
    assert not any("ypass" in c.text() for c in w.findChildren(QCheckBox)), \
        "quedo la casilla vieja de Bypass"

    texto_off = b.text()
    b.setChecked(True)
    _app.processEvents()
    assert w._pipeline.bypass, "el boton no llego al pipeline"
    assert b.text() != texto_off, "el boton no cambia de texto al activarse"
    # El estado activo se pinta con la regla global QPushButton:checked, no con un
    # estilo inline: asi los tres botones de la fila (y ACTIVAR) se ven igual sin
    # repetir el color en cada uno. Antes el Mute traia el suyo propio y quedaba
    # con letra roja sobre el fondo rojo del :checked.
    assert not b.styleSheet(),         "estilo inline en el boton: pisa la regla global QPushButton:checked"

    b.setChecked(False)
    _app.processEvents()
    assert not w._pipeline.bypass
    assert b.text() == texto_off, "no restaura el texto normal"
    print("Bypass: boton en la fila de Grabar/Mute      OK")


def test_botones_de_escucha_mismo_ancho_y_sin_recortes():
    """Grabar / Bypass / Mute comparten ancho, y su texto no sale recortado.

    Los tres son la misma clase de control, uno al lado del otro: anchos distintos
    se ven como un descuido. Y el ancho tiene que alcanzar para el texto de CADA
    estado — antes los tres mostraban el estado activo con '...' porque el fijo se
    habia elegido mirando solo el texto en reposo.
    """
    from PySide6.QtCore import Qt
    from ui.main_window import _ACTION_BTN_W

    w = _win()
    anchos = {b.width() for b in (w._btn_record, w._btn_bypass, w._btn_mute)}
    assert anchos == {_ACTION_BTN_W}, f"anchos distintos: {anchos}"

    fm = w._btn_record.fontMetrics()
    disponible = _ACTION_BTN_W - 14          # borde + padding del QPushButton
    recortados = []
    for b, textos in ((w._btn_record, ("⏺  Grabar", "⏹  Detener")),
                      (w._btn_bypass, ("⇄  Bypass", "⇄  Crudo"))):
        for txt in textos:
            s = tr(txt)
            if fm.elidedText(s, Qt.ElideRight, disponible) != s:
                recortados.append(s)
    assert not recortados, f"texto recortado en {_ACTION_BTN_W}px: {recortados}"
    print("Botones de escucha: mismo ancho, sin recortes OK")


def test_indicadores_vuelven_a_reposo_al_detener():
    """Al DETENER, ningun indicador puede quedar con el ultimo valor medido.

    Los que se pintan solo en `_tick_levels` son los expuestos: ese timer se
    detiene junto con el proceso, asi que sin un reset explicito muestran
    actividad de algo que ya no corre (invariante 5). Se reporto con el AGC de
    entrada; le pasaba lo mismo al limitador, al S/N y a los marcadores de
    heterodino.
    """
    w = _win()
    vivos = {
        "AGC de entrada":  (w._label_agc_gain, "+18 dB"),
        "limitador":       (w._lbl_peak_active, "ACTIVO  -4.2 dB"),
        "nivelador":       (w._lbl_leveler, "+7.5 dB"),
        "nivelador (Avanzada)": (w._adv_audio_tab._lbl_leveler_act, "+7.5 dB"),
        "periodicidad (Avanzada)": (w._adv_audio_tab._lbl_period_act, "periodicidad 0.62 → nivel entero"),
        "techo del AGC":   (w._lbl_agc_ceiling, "piso -45 dBFS · limitando a +9 dB"),
        "S/N":             (w._lbl_snr, "S/N: +12 dB"),
        "latencia":        (w._label_latency, "Latencia: 40 ms"),
    }
    for lbl, texto in vivos.values():
        lbl.setText(texto)
    w._cpu_meter.set_load(87.0)

    w._reset_live_indicators()

    pegados = [n for n, (lbl, texto) in vivos.items() if lbl.text() == texto]
    assert not pegados, f"indicadores congelados tras detener: {pegados}"
    for n, (lbl, _) in vivos.items():
        assert "—" in lbl.text() or "--" in lbl.text(), \
            f"{n} no quedo en reposo: {lbl.text()!r}"
    assert w._cpu_meter._load_pct == 0.0, "medidor de CPU no volvio a reposo al detener"
    print("Indicadores vuelven a reposo al detener      OK")


def test_dispositivo_perdido_detiene_y_avisa():
    """Si el dispositivo deja de responder en pleno proceso (interfaz USB caida,
    driver trabado), el tick de la GUI lo detecta via `audio_device_lost`,
    detiene como si se hubiera pulsado DETENER y avisa con un cartel. Antes la
    app quedaba en 'Procesando...' con silencio y el DETENER posterior se
    bloqueaba en PortAudio para siempre. Sin hardware: el pipeline arranca
    headless y el stream es un doble con device_lost=True."""
    from PySide6.QtWidgets import QMessageBox

    w = _win()
    orig_start = w._pipeline.start
    w._pipeline.start = lambda: orig_start(headless=True)
    cajas = []
    orig_warn = QMessageBox.warning
    QMessageBox.warning = staticmethod(lambda *a, **k: cajas.append(a[1]) or 0)
    try:
        w._btn_start.click()
        _app.processEvents()
        assert w._pipeline.is_running() and w._btn_start.isChecked()
        assert w._level_timer.isActive()

        class _StreamPerdido:
            device_lost = True
            overruns = underruns = 0
            def stop(self): pass

        w._pipeline._stream = _StreamPerdido()
        assert w._pipeline.audio_device_lost
        w._tick_levels()
        _app.processEvents()

        assert not w._pipeline.is_running(), "el pipeline sigue corriendo"
        assert not w._btn_start.isChecked(), "ACTIVAR sigue marcado"
        assert "ACTIVAR" in w._btn_start.text()
        assert not w._level_timer.isActive(), "el timer de niveles sigue activo"
        assert w._combo_in.isEnabled() and w._btn_refresh_devices.isEnabled()
        assert cajas and "no responde" in cajas[0], cajas
        assert "dejó de responder" in w._status_bar.currentMessage()
        # sin stream, el tick posterior no vuelve a disparar el aviso
        w._tick_levels()
        assert len(cajas) == 1
    finally:
        QMessageBox.warning = orig_warn
        w._pipeline.start = orig_start
        w.close()
    print("Dispositivo perdido: detiene y avisa         OK")


def test_boton_activo_letra_amarilla_y_negrita():
    """Cualquier boton activado se pone rojo (regla global QPushButton:checked):
    la letra tiene que ir en amarillo y negrita para que se lea.

    Antes cada boton traia su estilo inline y no coincidian: el Mute usaba rojo
    (#ef5350) SOBRE el fondo rojo del :checked, y Grabar y ACTIVAR se quedaban con
    el gris por defecto. Un estilo inline en el widget PISA la regla global, asi
    que el guard exige las dos cosas: que la regla este, y que ningun boton de la
    fila la sobreescriba.
    """
    w = _win()
    hoja = w.styleSheet()
    assert "QPushButton:checked" in hoja
    regla = hoja.split("QPushButton:checked", 1)[1].split("}", 1)[0]
    assert "#ffd600" in regla, f"la letra del boton activo no es amarilla: {regla}"
    assert "bold" in regla, f"la letra del boton activo no es negrita: {regla}"

    for nombre, b in (("Grabar", w._btn_record), ("Bypass", w._btn_bypass),
                      ("Mute", w._btn_mute), ("ACTIVAR", w._btn_start)):
        assert not b.styleSheet(),             f"{nombre} tiene estilo inline y pisa la regla global: {b.styleSheet()!r}"
    print("Boton activo: letra amarilla y negrita        OK")


def test_mute_button_gating_and_state():
    """El boton Mute arranca deshabilitado (requiere proceso); al togglear
    llama set_output_mute y cambia texto/estilo; destogglear lo restaura."""
    w = _win()
    assert not w._btn_mute.isEnabled(), "Mute deberia arrancar deshabilitado (sin proceso)"

    calls = []
    orig = w._pipeline.set_output_mute
    w._pipeline.set_output_mute = lambda v: calls.append(v)
    normal = w._btn_mute.text()
    try:
        w._btn_mute.setChecked(True)
        assert calls and calls[-1] is True, "toggle Mute no llamo set_output_mute(True)"
        # El aviso visual lo da la regla global QPushButton:checked (fondo rojo +
        # letra amarilla). Lo propio del boton es cambiar de TEXTO; comprobar su
        # styleSheet() era comprobar justo lo que se saco a proposito.
        assert w._btn_mute.text() != normal, "Mute activo no cambia de texto"
        w._btn_mute.setChecked(False)
        assert calls[-1] is False, "destoggle Mute no llamo set_output_mute(False)"
        assert w._btn_mute.text() == normal, "Mute inactivo no restaura el texto"
    finally:
        w._pipeline.set_output_mute = orig
    print("Mute: gating + estado del boton              OK")


def test_update_button_and_skip():
    """Aviso de version nueva: el boton esta oculto al arrancar (sin red); un checker en
    AVAILABLE lo muestra con la version; 'Omitir' lo oculta y persiste; el chequeo
    automatico respeta 'omitida' pero el manual no."""
    import updater
    from ui.update_dialog import UpdateDialog

    w = _win()
    assert not w._btn_update.isVisible(), "el aviso no debe verse al arrancar"
    assert w._update_checker.state == updater.UpdateChecker.IDLE, "no debe consultar solo en el test"

    res = {"tag": "v9.9", "version": "9.9.0", "label": "v9.9", "notes": "## Novedades\n- algo",
           "url": "https://example.invalid/r", "published": ""}

    class _Fake:
        state = updater.UpdateChecker.AVAILABLE
        message = ""
        result = res

        def is_running(self):
            return False

    w._update_checker = _Fake()
    w._update_manual = False
    w._poll_update()
    w.show()
    assert w._btn_update.isVisible() and "v9.9" in w._btn_update.text()
    assert w._config.update.last_check, "anota la consulta"

    # Omitir: el dialogo devuelve SKIP -> se oculta y persiste
    orig_exec = UpdateDialog.exec
    UpdateDialog.exec = lambda self: setattr(self, "choice", UpdateDialog.SKIP)
    try:
        w._on_update_button()
    finally:
        UpdateDialog.exec = orig_exec
    assert not w._btn_update.isVisible() and w._config.update.skipped_version == "v9.9"

    # Chequeo automatico: version omitida no vuelve a mostrarse
    w._update_manual = False
    w._poll_update()
    assert not w._btn_update.isVisible()
    # Chequeo manual: ignora lo omitido (abre el dialogo)
    abierto = []
    UpdateDialog.exec = lambda self: abierto.append(self.choice)
    try:
        w._update_manual = True
        w._poll_update()
    finally:
        UpdateDialog.exec = orig_exec
    assert abierto and w._btn_update.isVisible()
    print("Actualizaciones: boton oculto, omitir persiste, manual ignora lo omitido  OK")


def test_eibi_tab_search_and_no_network():
    """La solapa EiBi: no toca la red al construirse; con una base guardada llena la tabla
    (en el aire primero), respeta la hora manual y persiste frecuencia/tolerancia."""
    import tempfile
    import eibi_db
    from datetime import datetime, timezone
    from PySide6.QtWidgets import QApplication
    from ui.eibi_tab import EibiTab

    def sin_red(req, timeout):
        raise AssertionError("la solapa no debe tocar la red en este test")

    store = eibi_db.EibiStore(tempfile.mkdtemp(prefix="rnk_eibi_ui_"))
    now = datetime(2026, 10, 10, 19, 30, tzinfo=timezone.utc)   # sabado
    rows = ["6140;1900-2000;Mo-Fr;ARG;Radio Argentina;S;LAm;;1;;",
            "6140;0000-2400;;B;Radio Casa;P;LAm;;1;;"]
    relleno = ["%d;0000-2400;;X;R%d;E;Eu;;1;;" % (3000 + i, i) for i in range(1200)]
    raw = "\n".join(["kHz:75;x;"] + rows + relleno).encode("latin-1")
    store.save("a26", raw, "", "", now)
    updater = eibi_db.EibiUpdater(store, sin_red, lambda: now)
    orig_now = eibi_db._now_utc
    eibi_db._now_utc = lambda: now
    try:
        w = _win()
        cfg = w._config
        assert not w._eibi_tab._shown_once, "no debe cargar ni bajar nada antes de mostrarse"
        tab = EibiTab(cfg, updater)
        cfg.eibi.auto_update = False          # esta prueba no verifica el vencimiento
        tab.show()
        QApplication.processEvents()
        assert tab._db is not None and len(tab._db) > 1000
        tab._spin_freq.setValue(6140.0)
        tab._spin_tol.setValue(1.0)
        assert tab._table.rowCount() == 2
        assert tab._table.item(0, 5).text() == "Radio Casa" and tab._table.item(0, 0).text() == "●"
        assert tab._table.item(1, 0).text() == "○"            # Mo-Fr y hoy es sabado
        assert cfg.eibi.freq_khz == 6140.0 and cfg.eibi.tol_khz == 1.0
        # hora manual: lunes 19:30 -> Radio Argentina pasa a estar en el aire
        tab._chk_now.setChecked(False)
        tab._combo_day.setCurrentIndex(0)
        tab._edit_time.setTime(tab._edit_time.time().fromString("19:30", "HH:mm"))
        stations = {tab._table.item(r, 5).text(): tab._table.item(r, 0).text()
                    for r in range(tab._table.rowCount())}
        assert stations["Radio Argentina"] == "●", stations
        tab._spin_freq.setValue(9999.0)
        assert tab._table.rowCount() == 0 and "Sin coincidencias" in tab._lbl_result.text()
        tab.close()
    finally:
        eibi_db._now_utc = orig_now
    print("EiBi: solapa busca, ordena, hora manual y no usa la red  OK")


def test_translate_tab_warning_and_not_installed():
    """La pestaña Traducción: el banner de advertencia está siempre visible
    (no es opcional, lo pidió el usuario explícito) y, sin rutas de worker
    configuradas, el estado dice 'no instalado' sin crashear."""
    w = _win()
    tab = w._translate_tab
    # El banner es un QLabel con el texto de advertencia — buscarlo por
    # contenido en vez de por posición/atributo interno, así sobrevive a
    # reordenar el layout.
    from PySide6.QtWidgets import QLabel
    labels = [lbl.text() for lbl in tab.findChildren(QLabel)]
    assert any("aproximada" in t and "confiable" in t for t in labels), \
        f"no se encontró el banner de advertencia: {labels}"

    assert w._config.translate.worker_python_path == "", "config default deberia venir vacia"
    # Sin modulo instalado ni rutas manuales: Iniciar NO lanza nada, guia a
    # instalar. El panel de instalacion es visible; nada se descarga solo.
    import translate_installer as inst
    assert not inst.is_installed()
    w.show()
    w._tabs.setCurrentWidget(tab)
    tab._refresh_install_ui()
    assert tab._install_box.isVisible() and tab._btn_install.isVisible()
    assert not tab._progress.isVisible()
    assert not tab._btn_toggle.isEnabled(), 'Iniciar activo sin modulo instalado'
    assert not tab._combo_src.isEnabled() and not tab._combo_dst.isEnabled()
    tab._btn_toggle.setChecked(True)
    assert not tab._active, "no deberia haber arrancado sin modulo instalado"
    assert "instal" in tab._lbl_status.text().lower(), tab._lbl_status.text()
    from translate_client import TranslateClient
    assert w._translate_client.state == TranslateClient.STOPPED
    QApplication.processEvents()   # singleShot(0): vuelve a destildar el boton
    assert not tab._btn_toggle.isChecked()
    # Con rutas manuales (Configuracion avanzada) el panel se oculta.
    w._config.translate.worker_python_path = "x"
    w._config.translate.worker_script_path = "y"
    tab._refresh_install_ui()
    assert not tab._install_box.isVisible()
    assert tab._btn_toggle.isEnabled() and tab._combo_src.isEnabled()
    w._config.translate.worker_python_path = ""
    w._config.translate.worker_script_path = ""
    print("Traduccion: banner siempre visible + no instalado   OK")


def test_translate_tab_show_mode():
    """El combo 'Mostrar' (origen/traduccion/ambos) controla el formato de
    cada linea de subtitulo, y la eleccion se persiste en config."""
    w = _win()
    tab = w._translate_tab
    assert tab._combo_show.count() == 3

    seg = {"start": 1.0, "text": "hola", "translated": "hello"}
    casos = {"both": ("hola", "hello"), "src": ("hola",), "dst": ("hello",)}
    for mode, esperados in casos.items():
        w._config.translate.show_mode = mode
        texto = tab._format_segment(seg)
        for e in esperados:
            assert e in texto, f"modo {mode!r}: {texto!r} no tiene {e!r}"
        if mode == "src":
            assert "hello" not in texto, f"modo 'src' no deberia mostrar la traduccion: {texto!r}"
        if mode == "dst":
            assert "hola" not in texto, f"modo 'dst' no deberia mostrar el original: {texto!r}"

    for i in range(tab._combo_show.count()):
        if tab._combo_show.itemData(i) == "src":
            tab._combo_show.setCurrentIndex(i)
            break
    assert w._config.translate.show_mode == "src", "el combo no actualizo la config"
    print("Traduccion: combo Mostrar controla el formato        OK")


def test_translate_tab_format_segment_sin_translated_no_crashea():
    """_format_segment() no debe lanzar KeyError si un segmento llega sin
    'translated' (ej. un proceso worker viejo que quedo corriendo de antes
    de agregar low_confidence — paso de verdad: tumbaba _tick en loop hasta
    reiniciar la app). Degrada mostrando el texto original."""
    w = _win()
    tab = w._translate_tab
    seg = {"start": 0.0, "end": 1.0, "text": "hola"}   # sin "translated"
    w._config.translate.show_mode = "both"
    assert tab._format_segment(seg) == "hola  →  hola"
    w._config.translate.show_mode = "dst"
    assert tab._format_segment(seg) == "hola"
    print("Traduccion: segmento sin 'translated' no crashea     OK")


def test_translate_tab_clear_button():
    """El boton Borrar vacia la lista de subtitulos sin tocar el estado
    de la traduccion (activa o detenida)."""
    w = _win()
    tab = w._translate_tab
    from PySide6.QtWidgets import QListWidgetItem
    tab._list.addItem(QListWidgetItem("linea 1"))
    tab._list.addItem(QListWidgetItem("linea 2"))
    assert tab._list.count() == 2

    tab._on_clear()
    assert tab._list.count() == 0, "Borrar no vacio la lista"
    assert not tab._active, "Borrar no deberia activar la traduccion"

    tab._config.translate.worker_python_path = 'x'
    tab._config.translate.worker_script_path = 'y'
    tab._btn_toggle.setChecked(True)
    tab._list.addItem(QListWidgetItem("linea 3"))
    tab._on_clear()
    assert tab._list.count() == 0
    assert tab._active, "Borrar no deberia detener una traduccion activa"
    tab._btn_toggle.setChecked(False)
    print("Traduccion: boton Borrar vacia la lista              OK")


def test_translate_tab_copy_to_clipboard():
    """Copiar (Ctrl+C o menu contextual) pone el texto en el portapapeles:
    sin seleccion copia todo, con seleccion copia solo lo seleccionado."""
    from PySide6.QtWidgets import QApplication, QListWidgetItem
    w = _win()
    tab = w._translate_tab
    tab._list.addItem(QListWidgetItem("linea uno"))
    tab._list.addItem(QListWidgetItem("linea dos"))

    tab._copy_selected()
    assert QApplication.clipboard().text() == "linea uno\nlinea dos", \
        "sin seleccion deberia copiar todas las lineas"

    tab._list.item(0).setSelected(True)
    tab._copy_selected()
    assert QApplication.clipboard().text() == "linea uno", \
        "con seleccion deberia copiar solo lo seleccionado"
    print("Traduccion: copiar al portapapeles (todo/seleccion)  OK")


def test_translate_tab_min_confidence_slider_persists():
    """El slider 'Confianza minima' persiste en config y se carga desde
    config (mismo patron que test_gate_threshold_slider_on_principal)."""
    w = _win()
    tab = w._translate_tab
    assert abs(tab._slider_min_confidence.value() - 50.0) < 0.01, \
        "default de fabrica deberia ser 50%"

    tab._slider_min_confidence.set_value(20.0)
    tab._slider_min_confidence.set_value(75.0, emit=True)
    _app.processEvents()
    assert abs(w._config.translate.min_confidence - 0.75) < 0.01, \
        w._config.translate.min_confidence

    w._config.translate.min_confidence = 0.1
    w._translate_tab._load_values()
    assert abs(tab._slider_min_confidence.value() - 10.0) < 0.01
    print("Traduccion: slider Confianza minima persiste         OK")


def test_translate_tab_low_confidence_warning():
    """Un resultado con low_confidence=True muestra SOLO el aviso (sin el
    texto transcripto) y no contamina el indicador de idioma/latencia
    promedio — es justo lo que pidio el usuario: saber que ese tramo de
    audio se perdio, en vez de quedar en silencio sin explicacion."""
    from translate_client import TranslateClient
    w = _win()
    tab = w._translate_tab
    tab._active = True
    w._translate_client._state = TranslateClient.READY   # sin proceso real

    msg = {"ok": True, "low_confidence": True, "detected_lang_prob": 0.34,
           "detected_lang": "nn",
           "segments": [{"start": 0.0, "end": 8.0, "text": "texto que no deberia verse"}]}
    orig_pop = w._translate_client.pop_results
    orig_chunk = w._pipeline.pop_translate_chunk
    w._translate_client.pop_results = lambda: [msg]
    w._pipeline.pop_translate_chunk = lambda seconds: None
    try:
        tab._tick()
        assert tab._list.count() == 1, "deberia agregar exactamente una linea de aviso"
        texto = tab._list.item(0).text()
        assert "34" in texto, f"deberia mostrar el % de confianza: {texto!r}"
        assert "texto que no deberia verse" not in texto, \
            f"no debe mostrar el texto transcripto con baja confianza: {texto!r}"
        assert len(tab._recent) == 0, \
            "low_confidence no debe alimentar el indicador de idioma/latencia"
    finally:
        w._translate_client.pop_results = orig_pop
        w._pipeline.pop_translate_chunk = orig_chunk
        tab._active = False
    print("Traduccion: aviso de confianza baja, sin contaminar el indicador  OK")


def test_translate_tab_music_notice_not_repeated():
    """Un tramo sin voz (musica/ruido) muestra UN aviso, no traduce nada, no
    contamina el indicador de idioma y no se repite si llegan varios seguidos."""
    from translate_client import TranslateClient
    w = _win()
    tab = w._translate_tab
    tab._active = True
    w._translate_client._state = TranslateClient.READY
    msg = {"ok": True, "music": True, "low_confidence": False,
           "detected_lang": "en", "detected_lang_prob": 0.2, "segments": []}
    orig_pop = w._translate_client.pop_results
    orig_chunk = w._pipeline.pop_translate_chunk
    w._pipeline.pop_translate_chunk = lambda seconds: None
    try:
        w._translate_client.pop_results = lambda: [dict(msg), dict(msg)]
        tab._tick()
        w._translate_client.pop_results = lambda: [dict(msg)]
        tab._tick()
        assert tab._list.count() == 1, "los avisos de musica seguidos deben colapsar"
        assert "sin voz" in tab._list.item(0).text().lower()
        assert len(tab._recent) == 0
        # una linea de voz real despues, y de nuevo musica: ahora SI vuelve a avisar
        w._translate_client.pop_results = lambda: [
            {"ok": True, "detected_lang": "en", "latency_s": 1.0,
             "segments": [{"text": "hello", "translated": "hola"}]}, dict(msg)]
        tab._tick()
        assert tab._list.count() == 3
    finally:
        w._translate_client.pop_results = orig_pop
        w._pipeline.pop_translate_chunk = orig_chunk
        tab._active = False
    print("Traduccion: aviso de musica sin repetirse  OK")


def test_translate_tab_detected_lang_and_avg_latency():
    """El indicador de idioma detectado + latencia promedio reemplaza el
    timestamp por linea: se alimenta de los ultimos resultados (hasta 5) y
    se resetea al Detener."""
    w = _win()
    tab = w._translate_tab

    assert "—" in tab._lbl_stats.text(), "arranca en reposo sin dato"

    # Ningun segmento lleva ya timestamp propio.
    seg = {"start": 3.0, "text": "hola", "translated": "hello"}
    assert "3" not in tab._format_segment(seg), \
        f"el timestamp por linea deberia haberse quitado: {tab._format_segment(seg)!r}"

    for lang, lat in [("en", 4.0), ("en", 6.0), ("zh", 5.0)]:
        tab._recent.append((lang, lat))
    tab._refresh_stats_label()
    texto = tab._lbl_stats.text()
    assert "zh" in texto, f"deberia mostrar el idioma mas reciente (zh): {texto!r}"
    assert "5.0" in texto, f"promedio esperado (4+6+5)/3=5.0: {texto!r}"

    tab._config.translate.worker_python_path = 'x'
    tab._config.translate.worker_script_path = 'y'
    tab._btn_toggle.setChecked(True)
    tab._btn_toggle.setChecked(False)
    assert len(tab._recent) == 0, "Detener deberia limpiar el historial"
    assert "—" in tab._lbl_stats.text(), "Detener deberia volver el indicador a reposo"
    print("Traduccion: idioma detectado + latencia promedio     OK")


def test_detener_procesamiento_detiene_traduccion():
    """Al DETENER el procesamiento general, si la traduccion estaba activa
    se detiene tambien: sin audio entrando al buffer, el worker quedaba
    prendido esperando chunks que nunca llegan (reportado por el usuario)."""
    w = _win()
    w._pipeline.start(headless=True)
    try:
        w._translate_tab._config.translate.worker_python_path = 'x'
        w._translate_tab._config.translate.worker_script_path = 'y'
        w._translate_tab._btn_toggle.setChecked(True)
        assert w._translate_tab._active, "no se activo la traduccion"

        w._on_toggle_processing(False)   # simula DETENER

        assert not w._translate_tab._active, \
            "DETENER no detuvo la traduccion que estaba activa"
        assert not w._translate_tab._btn_toggle.isChecked(), \
            "el boton Iniciar/Detener de Traduccion no refleja el estado"
    finally:
        w._pipeline.stop()
    print("DETENER general tambien detiene la traduccion      OK")


def test_detener_procesamiento_no_rompe_si_traduccion_inactiva():
    """DETENER sin que la traduccion estuviera corriendo no debe fallar."""
    w = _win()
    w._pipeline.start(headless=True)
    try:
        assert not w._translate_tab._active
        w._on_toggle_processing(False)   # no debe lanzar excepcion
    finally:
        w._pipeline.stop()
    print("DETENER sin traduccion activa no rompe             OK")


def test_about_dialog():
    """El botón ℹ de la barra de estado abre el 'Acerca de' sin crashear."""
    from PySide6.QtWidgets import QMessageBox
    w = _win()
    assert w._btn_about.text() == "ℹ", "falta el boton Acerca de"
    orig = QMessageBox.exec
    QMessageBox.exec = lambda self: 0          # no bloquear el test
    try:
        w._show_about()                        # construye el dialogo (HTML, icono)
    finally:
        QMessageBox.exec = orig
    print("Acerca de: boton + dialogo                  OK")


def test_about_donate_button():
    """Boton de donacion: aparece SOLO con _DONATE_URL configurada, y al
    clickearlo abre esa URL. Sin URL no debe existir el boton (asi un
    placeholder no puede viajar en un release hacia una pagina rota)."""
    from PySide6.QtWidgets import QMessageBox
    import ui.main_window as mw

    w = _win()
    cajas = []
    orig_exec, orig_url = QMessageBox.exec, mw.QDesktopServices.openUrl
    abiertas = []
    QMessageBox.exec = lambda self: cajas.append(self) or 0
    mw.QDesktopServices.openUrl = lambda u: abiertas.append(u.toString())
    url_orig = mw._DONATE_URL
    try:
        # --- sin URL configurada: no hay boton de donacion ---
        mw._DONATE_URL = ""
        cajas.clear()
        w._show_about()
        textos = [b.text() for b in cajas[-1].buttons()]
        assert not any("café" in t or "coffee" in t for t in textos), \
            f"boton de donacion presente sin URL configurada: {textos}"

        # --- con URL: aparece y abre el navegador al clickearlo ---
        mw._DONATE_URL = "https://paypal.me/ejemplo"
        cajas.clear()
        w._show_about()
        box = cajas[-1]
        donar = [b for b in box.buttons()
                 if "café" in b.text() or "coffee" in b.text()]
        assert donar, f"falta el boton de donacion: {[b.text() for b in box.buttons()]}"
        assert box.buttons(), "el dialogo quedo sin boton de cerrar"

        # Simular que el usuario lo clickeo: _show_about consulta clickedButton()
        # DESPUES de exec(), asi que hay que dejarlo elegido antes de volver.
        cajas.clear()
        QMessageBox.exec = lambda self: (cajas.append(self),
                                         self.setResult(0),
                                         _click_donar(self))[0] or 0
        abiertas.clear()
        w._show_about()
        assert abiertas == ["https://paypal.me/ejemplo"], \
            f"no se abrio la URL de donacion: {abiertas}"
    finally:
        QMessageBox.exec = orig_exec
        mw.QDesktopServices.openUrl = orig_url
        mw._DONATE_URL = url_orig
    print("Acerca de: boton de donacion                OK")


def _click_donar(box) -> None:
    """Marca el boton de donacion como el clickeado, sin mostrar el dialogo."""
    for b in box.buttons():
        if "café" in b.text() or "coffee" in b.text():
            b.click()
            return


def test_export_diagnostics_button():
    """El botón 🩺 de la barra de estado empaqueta settings.json,
    errores_dsp.log (si existe), el preset activo y el volcado de estado
    interno en un .zip."""
    import zipfile
    import ui.main_window as mw

    w = _win()
    tmp_zip = os.path.join(tempfile.gettempdir(), "___rnk_test_diag___.zip")
    orig_save = mw.QFileDialog.getSaveFileName
    try:
        # Preset activo, para que aparezca dentro del zip.
        w._preset_manager.save(_PRESET_DE_PRUEBA, w._config)
        w._presets_tab._refresh_list()
        w._presets_tab._select_by_name(_PRESET_DE_PRUEBA)
        w._presets_tab._on_load()
        _app.processEvents()

        # Generar algo de errores_dsp.log, para que el zip tenga algo que
        # empaquetar ahí también (si no existe, _export_diagnostics lo omite).
        w._pipeline.log_diagnostic("test_export_diagnostics_button", "linea de prueba")

        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
        mw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (tmp_zip, ""))
        w._export_diagnostics()

        assert os.path.exists(tmp_zip), "_export_diagnostics no escribio el .zip"
        with zipfile.ZipFile(tmp_zip) as zf:
            nombres = zf.namelist()
            assert "settings.json" in nombres
            assert "errores_dsp.log" in nombres
            assert any(n.startswith("preset_") for n in nombres), \
                f"falta el preset activo en el zip: {nombres}"
            assert "diagnostico.txt" in nombres
            assert zf.read("diagnostico.txt").decode("utf-8").strip()
        print("Exportar diagnostico: boton -> .zip completo   OK")
    finally:
        mw.QFileDialog.getSaveFileName = orig_save
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)


def test_auto_load_respects_saved_mode():
    """El auto-cargar un perfil nombrado fuerza estático; NO debe hacerlo si el
    modo guardado era MCRA (regresión: un last_noise_profile viejo pisaba el
    modo Adaptativo elegido por el usuario en cada arranque)."""
    w = _win()
    # Simular sesión previa en MCRA con un perfil nombrado persistido
    w._config.dsp.noise_mode = "mcra"
    w._config.last_noise_profile = "cualquiera"
    ret = w._auto_load_noise_profile()
    assert ret is None, "auto-load no debe cargar en modo MCRA"
    assert w._config.dsp.noise_mode == "mcra", "auto-load piso el modo MCRA a estático"
    print("Auto-load respeta el modo MCRA guardado    OK")


def test_bypass_remembers_output_gain():
    """La ganancia de Salida se recuerda por modo bypass (A/B a nivel parejo):
    al alternar Bypass el slider salta al valor guardado del modo destino, sin
    reajustar cada vez."""
    w = _win()
    assert not w._btn_bypass.isChecked(), "arranca sin bypass"
    init_bypass = w._out_gain_by_bypass[True]     # valor inicial (== config)

    # Ajuste en modo procesando → se recuerda en el slot False
    w._s_gain_out.set_value(-5.0, emit=True)
    assert w._out_gain_by_bypass[False] == -5.0, "no recordo la ganancia de procesando"

    # Pasar a bypass: el slider salta al valor guardado de bypass
    w._btn_bypass.setChecked(True)
    assert abs(w._s_gain_out.value() - init_bypass) < 1e-6, "no restauro el valor de bypass"
    assert abs(w._pipeline._output_gain - 10 ** (init_bypass / 20.0)) < 1e-4, \
        "el pipeline no recibio la ganancia de bypass"

    # Ajuste distinto en bypass → se recuerda en el slot True
    w._s_gain_out.set_value(3.0, emit=True)
    assert w._out_gain_by_bypass[True] == 3.0, "no recordo la ganancia de bypass"

    # Volver a procesando: recupera -5.0; y de nuevo a bypass: recupera 3.0
    w._btn_bypass.setChecked(False)
    assert abs(w._s_gain_out.value() - (-5.0)) < 1e-6, "no restauro el valor de procesando"
    w._btn_bypass.setChecked(True)
    assert abs(w._s_gain_out.value() - 3.0) < 1e-6, "no recordo el valor de bypass en el 2do toggle"
    print("Bypass recuerda ganancia de salida (A/B)   OK")


def test_bypass_clears_status_bar_message():
    """Al salir de Bypass, el aviso 'Bypass activo...' de la barra de estado
    se borra — antes quedaba pegado para siempre (showMessage sin timeout no
    se limpia solo). Con el proceso corriendo, además vuelve a mostrar
    'Procesando...' (el estado real), no la barra en blanco."""
    w = _win()
    bypass_msg = tr("Bypass activo — se escucha la señal cruda, sin procesar.")

    # Sin procesamiento activo: al salir de Bypass solo se limpia (no hay
    # "Procesando..." que restaurar).
    w._btn_bypass.setChecked(True)
    assert w._status_bar.currentMessage() == bypass_msg
    w._btn_bypass.setChecked(False)
    assert w._status_bar.currentMessage() != bypass_msg, \
        "el aviso de Bypass quedo pegado en la barra de estado"

    # No debe pisar un aviso mas importante que haya aparecido en el medio
    # (p. ej. un error del DSP).
    w._btn_bypass.setChecked(True)
    otro_aviso = tr("otro aviso mas importante")
    w._status_bar.showMessage(otro_aviso)
    w._btn_bypass.setChecked(False)
    assert w._status_bar.currentMessage() == otro_aviso, \
        "salir de Bypass piso un aviso que no era el suyo"

    # Con el proceso corriendo: al salir de Bypass vuelve "Procesando...".
    w._btn_bypass.setChecked(False)
    w._pipeline.start(headless=True)
    try:
        w._btn_bypass.setChecked(True)
        assert w._status_bar.currentMessage() == bypass_msg
        w._btn_bypass.setChecked(False)
        assert w._status_bar.currentMessage() == tr("Procesando..."), \
            f"no volvio el aviso de Procesando: {w._status_bar.currentMessage()!r}"
    finally:
        w._pipeline.stop()
    print("Bypass limpia su aviso de la barra de estado  OK")


def test_dsp_error_is_visible():
    """Un fallo del hilo procesador tiene que VERSE, y el aviso no lo pisa el
    timer de 500 ms del cancelador.

    Sin esto el fallo es mudo: el manejador de errores resetea el profiler cada
    vez y en MCRA el cartel dice 'calibrando...' para siempre, sin nada que
    explique por que no hay reduccion ni piso de ruido. Ademas el callback lo
    invoca el HILO PROCESADOR, asi que no puede tocar widgets — solo guarda el
    texto y la GUI lo pinta en su propio tick."""
    w = _win()
    _set_combo(w._combo_noise_mode, "mcra")   # el modo donde se reporto el sintoma

    class _PipeFalso:
        dsp_error_count = 3
        dsp_last_error = "ValueError: shapes (961,) (7,)"
    real = w._pipeline
    w._pipeline = _PipeFalso()
    try:
        w._check_dsp_errors()
    finally:
        w._pipeline = real
    assert "errores_dsp.log" in w._label_noise.text(), \
        "el cartel del cancelador no avisa del fallo"
    assert "3" in w._status_bar.currentMessage(), \
        "la barra de estado no informa cuantos errores hubo"

    # El timer del cancelador NO debe pisar el aviso mientras esta vigente
    w._update_noise_db()
    assert "errores_dsp.log" in w._label_noise.text(), \
        "el timer de 500 ms piso el aviso de error"

    # Pasada la retencion, el cartel vuelve a su ciclo normal
    for _ in range(12):
        w._update_noise_db()
    assert "errores_dsp.log" not in w._label_noise.text(), \
        "el aviso quedo pegado para siempre"
    print("Aviso visible de error del DSP             OK")


def test_mcra_stall_reason():
    """Si MCRA no calibra, el cartel dice POR QUE, no 'calibrando...' para siempre.

    El warmup son ~200 ms; quedarse en ese texto indefinidamente fue lo que hizo
    indescifrable el sintoma reportado en el aire (no calibra, no reduce, no
    dibuja el piso, y el cartel tranquilo). Las cuatro causas se ven distinto."""
    w = _win()

    class _Pipe:
        bypass = False          # sin bypass: el aviso de falla SI corresponde
        dsp_error_count = 0
        noise_has_profile = False
        db_in = -20.0
        noise_mode = "mcra"
        post_filter_extra_db = 0.0
        mcra_diag = "frames=0 warmup=80"
        volcados = []
        input_level_db = None   # gate_enabled=False por default: no se usa
        gate_open = False

        def is_running(self):
            return True

        def log_diagnostic(self, titulo, detalle):
            self.volcados.append((titulo, detalle))

    w._pipeline = _Pipe()
    w._config.dsp.noise_enabled = True

    w._update_noise_db()
    assert "calibrando" in w._label_noise.text(), "no muestra el warmup normal"

    for _ in range(12):        # pasado el margen: tiene que explicar
        w._update_noise_db()
    generico = w._label_noise.text()
    assert "calibrando" not in generico, "se queda en 'calibrando' para siempre"

    w._config.dsp.noise_enabled = False
    w._update_noise_db()
    assert "desactivado" in w._label_noise.text(), "no detecta el cancelador apagado"

    w._config.dsp.noise_enabled = True
    _Pipe.db_in = -70.0
    w._update_noise_db()
    assert "audio de entrada" in w._label_noise.text(), "no detecta la falta de audio"

    _Pipe.db_in = -20.0
    # La rama "ninguna causa conocida" vuelca el estado interno al log UNA vez
    # por episodio: es la unica forma de saber que contador esta quieto, porque
    # las tres causas conocidas ya se descartaron cuando se reporto en el aire.
    assert len(_Pipe.volcados) == 1,         f"la rama desconocida no volco el diagnostico ({len(_Pipe.volcados)} veces)"

    _Pipe.dsp_error_count = 4
    w._update_noise_db()
    assert "errores_dsp.log" in w._label_noise.text(), "no prioriza el error del DSP"
    print("MCRA atascado: el cartel dice por que   OK")


def test_ui_scale_combo():
    """El combo de escala de UI vive en la barra de estado, guarda en config y
    NO toca nada del audio (es una preferencia de aplicacion, como el idioma)."""
    w = _win()
    combo = w._combo_ui_scale
    assert combo in w._status_bar.findChildren(type(combo)), "el combo no esta en la barra de estado"
    # La escala aplicada siempre esta ofrecida (aunque la pantalla sea chica)
    datos = [combo.itemData(i) for i in range(combo.count())]
    assert w._applied_ui_scale in datos, "la escala aplicada no figura en el combo"

    # Elegir otra escala la persiste; el resto de la config no se toca
    antes_dsp = w._config.dsp.noise_alpha
    otra = next((d for d in datos if d != w._config.window.ui_scale), None)
    if otra is not None:
        combo.setCurrentIndex(datos.index(otra))
        _app.processEvents()
        assert w._config.window.ui_scale == otra, "la escala elegida no se guardo en config"
    assert w._config.dsp.noise_alpha == antes_dsp, "cambiar la escala toco el DSP"
    print("Escala de UI: combo + persistencia         OK")


def test_ui_scales_that_fit():
    """El filtro por pantalla razona en px REALES: a mayor escala la ventana
    ocupa mas pantalla aunque su ancho logico no cambie. En una notebook de
    1366 entran las tres; en una de 1024 el 150% se cae del combo."""
    assert ui_scales_that_fit(1920, 1.0) == (1.0, 1.25, 1.5)
    assert ui_scales_that_fit(1366, 1.0) == (1.0, 1.25, 1.5)
    assert 1.5 not in ui_scales_that_fit(1024, 1.0), "ofrece 150% donde no entra"
    # La aplicada siempre esta, aunque no entre: si no, el combo no podria
    # mostrar el estado actual y no habria como bajarla.
    assert 1.5 in ui_scales_that_fit(800, 1.5)
    print("Escalas ofrecidas por tamano de pantalla   OK")


def test_read_ui_scale_tolerante():
    """main.py lee la escala ANTES de crear el QApplication: un settings.json
    roto, ausente o con un valor raro NO puede impedir que la app abra."""
    import json
    import tempfile as _tf
    d = _tf.mkdtemp(prefix="rnk_scale_")
    ok = os.path.join(d, "ok.json")
    with open(ok, "w", encoding="utf-8") as f:
        json.dump({"window": {"ui_scale": 1.25}}, f)
    assert read_ui_scale(ok) == 1.25
    roto = os.path.join(d, "roto.json")
    with open(roto, "w", encoding="utf-8") as f:
        f.write("{ esto no es json")
    assert read_ui_scale(roto) == 1.0, "un settings.json roto tiene que dar 1.0"
    assert read_ui_scale(os.path.join(d, "no_existe.json")) == 1.0
    raro = os.path.join(d, "raro.json")
    with open(raro, "w", encoding="utf-8") as f:
        json.dump({"window": {"ui_scale": 4.0}}, f)   # fuera de UI_SCALES
    assert read_ui_scale(raro) == 1.0, "una escala fuera de rango tiene que dar 1.0"
    shutil.rmtree(d, True)
    print("read_ui_scale tolerante a settings roto    OK")


def test_noise_fall_slider():
    """El slider del freno de caida del piso llega al DSP y respeta su gating.

    El clamp del setter tiene que coincidir con el rango del slider (invariante 1):
    aca se comprueba desde la UI, moviendo el slider a sus dos extremos y leyendo lo
    que quedo en el profiler.
    """
    w = MainWindow()
    tab = w._adv_canceller_tab
    row = tab._s_noise_fall
    prof = w._pipeline._noise_profiler

    # Parte de un valor distinto del que se va a probar: QSlider.setValue() no emite
    # valueChanged si el valor no cambia, y el test pasaria sin ejercitar el handler
    # (invariante 11).
    row.set_value(12.0)
    row.set_value(4.0, emit=True)
    _app.processEvents()
    assert abs(prof._fall_db_s - 4.0) < 0.01, prof._fall_db_s
    assert abs(w._config.dsp.noise_fall_db_s - 4.0) < 0.01

    row.set_value(30.0, emit=True)
    _app.processEvents()
    assert abs(prof._fall_db_s - 30.0) < 0.01, prof._fall_db_s

    # Gating: es un control del cancelador Y solo actua en Adaptativo (toca lambda_d).
    w._config.dsp.noise_mode = "mcra"
    w._config.dsp.noise_enabled = False
    tab.refresh_enabled_states()
    assert not row._slider.isEnabled(), "el slider queda activo sin el cancelador"
    w._config.dsp.noise_enabled = True
    tab.refresh_enabled_states()
    assert row._slider.isEnabled()
    w._config.dsp.noise_mode = "static"
    tab.refresh_enabled_states()
    assert not row._slider.isEnabled(), "el slider queda activo en Perfil estatico"

    w.close()
    print("slider del freno de caida del piso            OK")


def test_gate_threshold_slider_on_principal():
    """El umbral del Gate vive SOLO en Principal (sin duplicado en Avanzada
    Audio): mover el slider llega al DSP y a la config, y refresh_from_config
    lo sincroniza tras cargar un preset con otro umbral — misma fuente única
    de verdad que Intensidad y Post-Filtro."""
    w = MainWindow()
    gate = w._pipeline._gate

    assert not hasattr(w._adv_audio_tab, "_s_gate_threshold"), \
        "el umbral no deberia tener un slider duplicado en Avanzada Audio"

    w._slider_gate_threshold.set_value(-60.0)
    w._slider_gate_threshold.set_value(-35.0, emit=True)
    _app.processEvents()
    assert abs(gate._threshold_db - (-35.0)) < 0.01, gate._threshold_db
    assert abs(w._config.dsp.gate_threshold_db - (-35.0)) < 0.01

    # refresh_from_config (carga de preset en caliente) sincroniza el slider
    w._config.dsp.gate_threshold_db = -70.0
    w.refresh_from_config()
    assert abs(w._slider_gate_threshold.value() - (-70.0)) < 0.01, \
        w._slider_gate_threshold.value()

    # Gating: desactivar el módulo en Módulos Activos deshabilita el slider
    # (SliderRow deshabilita los hijos, no el contenedor — invariante del
    # proyecto: testear con _slider, no con el widget entero).
    w._chk_gate.setChecked(False)
    _app.processEvents()
    assert not w._slider_gate_threshold._slider.isEnabled(), \
        "el umbral sigue habilitado con el gate apagado"
    w._chk_gate.setChecked(True)
    _app.processEvents()
    assert w._slider_gate_threshold._slider.isEnabled(), \
        "el umbral no se re-habilita al activar el gate"

    w.close()
    print("slider de Umbral del Gate, solo en Principal  OK")


def test_mcra_en_bypass_no_es_falla():
    """En Bypass el estimador NO puede calibrar, y eso no es una falla.

    En bypass el audio no entra al hilo procesador, asi que el profiler queda en
    frames=0 / quar=0 / lambda_d=None con audio presente y cero errores: la firma
    EXACTA de un fallo real. Sin este caso, el aviso rojo salia cada vez que se
    dejaba el bypass puesto unos segundos para comparar, y mandaba a diagnosticar
    un problema inexistente (paso: se reporto como fallo de un preset del combo).
    """
    w = _win()
    w._config.dsp.noise_mode = "mcra"
    w._config.dsp.noise_enabled = True
    w._pipeline.set_noise_mode("mcra")
    w._pipeline.start(headless=True)
    w._pipeline._db_in = -30.0          # hay audio: no es la causa "sin entrada"

    w._pipeline.set_bypass(True)
    w._mcra_wait = 999                  # como si llevara rato sin calibrar
    w._update_noise_db()
    txt = w._label_noise.text()
    assert "Bypass" in txt, f"no explica el bypass: {txt!r}"
    assert "⚠" not in txt, f"lo reporta como falla: {txt!r}"
    assert "#ef5350" not in w._label_noise.styleSheet(), "lo pinta de rojo"
    assert w._mcra_wait == 0, "en bypass no debe acumular ticks de espera"

    # Y el volcado de diagnostico tiene que decirlo, que es lo que faltaba en el
    # log real y mando a buscar la causa al lado equivocado.
    assert "bypass=True" in w._pipeline.mcra_diag, w._pipeline.mcra_diag

    w._pipeline.set_bypass(False)
    w._pipeline.stop()
    w.close()
    print("MCRA en Bypass: no se reporta como falla     OK")


def test_bypass_indicadores_en_reposo():
    """En Bypass los indicadores del hilo procesador van a reposo.

    En bypass el audio no entra al hilo procesador: Reduccion activa, Reduccion
    extra, AGC, limitador, S/N... quedaban pegados en el ultimo valor medido y
    el cartel MCRA seguia diciendo "estimando en tiempo real", dando la
    sensacion de que el cancelador seguia actuando (reportado por el usuario).
    VU y latencia SI son validos en bypass (los alimenta el callback).
    """
    w = _win()
    w._config.dsp.noise_mode = "mcra"
    w._config.dsp.noise_enabled = True
    w._config.dsp.post_filter_enabled = True
    w._config.dsp.pitch_enhance_enabled = True
    w._pipeline.set_noise_mode("mcra")
    w._pipeline.start(headless=True)

    pipe_cls = type(w._pipeline)
    patched = {
        "noise_has_profile": property(lambda self: True),
        "noise_reduction_db": property(lambda self: -12.0),
        "post_filter_extra_db": property(lambda self: -6.0),
        "peak_reduction_db": property(lambda self: -4.0),
        "noise_voice_prob": property(lambda self: 0.8),
        "pitch_f0": property(lambda self: 150.0),
        "anf_notched_bins": property(lambda self: 2),
        "cpu_load_pct": property(lambda self: 42.0),
        "dropout_count": property(lambda self: 3),
        "worst_frame_ms": property(lambda self: 14.0),
    }
    canc, imp = w._adv_canceller_tab, w._adv_impulse_tab
    orig = {k: getattr(pipe_cls, k) for k in patched}
    for k, v in patched.items():
        setattr(pipe_cls, k, v)
    try:
        # Procesando: los indicadores muestran los valores vivos
        w._update_noise_db()
        w._tick_levels()
        assert "-12.0" in w._lbl_noise_db.text(), w._lbl_noise_db.text()
        assert "-6.0" in w._lbl_pf_extra.text(), w._lbl_pf_extra.text()
        assert "estimando" in w._label_noise.text(), w._label_noise.text()
        assert "ACTIVO" in w._lbl_peak_active.text(), w._lbl_peak_active.text()
        assert w._cpu_meter._load_pct == 42.0, w._cpu_meter._load_pct
        assert "3" in w._lbl_dropouts.text() and "14" in w._lbl_dropouts.text(), \
            w._lbl_dropouts.text()
        canc._update_stats(); imp._update_stats()
        assert "-12.0" in canc._lbl_noise_db.text(), canc._lbl_noise_db.text()
        assert "80%" in canc._lbl_noise_vp.text(), canc._lbl_noise_vp.text()
        assert "150" in canc._lbl_pitch_f0.text(), canc._lbl_pitch_f0.text()
        assert "2" in imp._lbl_anf_activity.text(), imp._lbl_anf_activity.text()

        # Bypass: todo lo que alimenta el hilo procesador va a reposo
        w._btn_bypass.setChecked(True)
        _app.processEvents()
        w._update_noise_db()
        w._tick_levels()
        canc._update_stats(); imp._update_stats()
        # Avanzada Cancelador y Supresor tambien (segunda vuelta del reporte)
        for lbl in (canc._lbl_noise_db, canc._lbl_pf_peak,
                    canc._lbl_pitch_f0, imp._lbl_anf_activity):
            assert "Bypass" in lbl.text(), f"indicador pegado en bypass: {lbl.text()!r}"
        for lbl in (canc._lbl_noise_vp, canc._lbl_pf_active):
            assert lbl.text() == "—", f"indicador pegado en bypass: {lbl.text()!r}"
        # Gate: mismo criterio, ahora en Principal + Avanzada Audio (dual).
        for lbl in (w._lbl_gate_floor, w._adv_audio_tab._lbl_gate_floor):
            assert "Bypass" in lbl.text(), f"indicador de gate pegado en bypass: {lbl.text()!r}"
        for lbl in (w._lbl_gate_state, w._adv_audio_tab._lbl_gate_state):
            assert lbl.text() == "—", f"indicador de gate pegado en bypass: {lbl.text()!r}"
        assert "-12.0" not in w._lbl_noise_db.text(),             f"Reduccion activa sigue mostrando un valor: {w._lbl_noise_db.text()!r}"
        assert "-6.0" not in w._lbl_pf_extra.text(),             f"Reduccion extra sigue mostrando un valor: {w._lbl_pf_extra.text()!r}"
        assert "estimando" not in w._label_noise.text() and "Bypass" in w._label_noise.text(),             f"el cartel MCRA no dice que esta en bypass: {w._label_noise.text()!r}"
        assert w._lbl_peak_active.text() == "—", w._lbl_peak_active.text()
        assert w._lbl_snr.text() == tr("S/N: —"), w._lbl_snr.text()
        assert w._cpu_meter._load_pct == 0.0, \
            f"medidor de CPU pegado en bypass: {w._cpu_meter._load_pct}"
        assert w._lbl_dropouts.text() == "—", \
            f"contador de cortes pegado en bypass: {w._lbl_dropouts.text()!r}"

        # Al salir del bypass vuelven los valores vivos
        w._btn_bypass.setChecked(False)
        _app.processEvents()
        w._update_noise_db()
        w._tick_levels()
        assert "-12.0" in w._lbl_noise_db.text()
        assert "estimando" in w._label_noise.text()
        assert w._cpu_meter._load_pct == 42.0, w._cpu_meter._load_pct
        canc._update_stats(); imp._update_stats()
        assert "80%" in canc._lbl_noise_vp.text()
        assert "2" in imp._lbl_anf_activity.text()
    finally:
        for k, v in orig.items():
            setattr(pipe_cls, k, v)
        w._pipeline.stop()
        w.close()
    print("Bypass: indicadores del DSP en reposo        OK")


def test_noise_freeze_slider():
    """El slider del freeze (Congelar piso con voz) llega al DSP en porcentaje.

    El control muestra 30-100 % y el DSP trabaja en 0.30-1.00: es el punto donde
    un factor 100 se puede perder en el camino sin que nada falle, salvo que el
    valor del profiler no coincida.
    """
    w = MainWindow()
    tab = w._adv_canceller_tab
    row = tab._s_noise_freeze
    prof = w._pipeline._noise_profiler

    row.set_value(50.0)
    row.set_value(70.0, emit=True)          # emit=True: setValue() solo no dispara
    _app.processEvents()
    assert abs(prof._freeze_thr - 0.70) < 0.01, prof._freeze_thr
    assert abs(w._config.dsp.noise_freeze_thr - 0.70) < 0.01

    row.set_value(100.0, emit=True)
    _app.processEvents()
    assert abs(prof._freeze_thr - 1.00) < 0.01, prof._freeze_thr

    w._config.dsp.noise_enabled = False
    tab.refresh_enabled_states()
    assert not row._slider.isEnabled(), "el slider queda activo sin el cancelador"
    w._config.dsp.noise_enabled = True
    tab.refresh_enabled_states()
    assert row._slider.isEnabled()

    w.close()
    print("slider del freeze del piso con voz            OK")


def test_all_sliders_have_tooltip():
    """Todo SliderRow de la app tiene texto de ayuda, y llega a los HIJOS.

    El tooltip sobre el contenedor no se ve nunca: el mouse siempre esta encima
    del label, del slider o del valor. Por eso SliderRow.setToolTip lo propaga y
    aca se verifica sobre el QSlider, que es donde el usuario apunta.
    Un slider nuevo sin entrada en ui/tooltips.py rompe este test a proposito."""
    w = _win()
    faltan = []
    for widget in (w, w._adv_audio_tab, w._adv_impulse_tab, w._adv_canceller_tab):
        for name, obj in vars(widget).items():
            if isinstance(obj, SliderRow) and not obj._slider.toolTip().strip():
                faltan.append(f"{type(widget).__name__}.{name}")
    assert not faltan, "sliders sin tooltip: " + ", ".join(sorted(faltan))
    # y que no sea un tooltip vacio de relleno: los textos son explicativos
    assert len(w._slider_noise._slider.toolTip()) > 60
    print("Tooltips en todos los sliders            OK")


def test_bypass_gain_persiste_entre_sesiones():
    """La ganancia A/B de bypass sobrevive al reinicio de la app.

    El mecanismo A/B funcionaba dentro de una sesion, pero los dos slots
    arrancaban con el MISMO valor, asi que en cada arranque volvia a "el mismo
    nivel en los dos modos" hasta ajustar de cada lado. Reportado en el aire
    justo despues de una tanda de reinicios: en la practica la funcion no
    llegaba a servir. El nivel de comparacion se calibra una vez, no por sesion.
    """
    w = _win()
    w._btn_bypass.setChecked(False)
    w._s_gain_out.set_value(-5.0, emit=True)
    _app.processEvents()
    w._btn_bypass.setChecked(True)
    w._s_gain_out.set_value(3.0, emit=True)
    _app.processEvents()
    w._save_settings()

    import json
    with open(settings_path(), encoding="utf-8") as f:
        g = json.load(f)["gain"]
    assert g["output_gain_db"] == -5.0, "el nivel de procesado no se guardo"
    assert g["output_gain_db_bypass"] == 3.0, "el nivel de bypass no se guardo"

    # Sesion nueva: los dos slots vuelven distintos
    w2 = _win()
    assert w2._out_gain_by_bypass[False] == -5.0
    assert w2._out_gain_by_bypass[True] == 3.0
    w2._btn_bypass.setChecked(True)
    _app.processEvents()
    assert abs(w2._s_gain_out.value() - 3.0) < 1e-6,         "al reabrir, el bypass no recupera su nivel"

    # Un preset NO lleva el nivel de bypass: describe como procesas, no a que
    # volumen escuchas la senal cruda.
    from presets import PresetManager as _PM
    cap = _PM._capture("x", w2._config)
    assert "output_gain_db_bypass" not in cap.get("gain", {}),         "el preset se llevo el nivel de bypass"
    print("Ganancia de bypass persiste entre sesiones  OK")


if __name__ == "__main__":
    test_tab_order()
    test_modules_group_moved_to_own_tab()
    test_post_filter_on_principal_autoenable()
    test_profile_buttons_visibility_by_mode()
    test_loaded_profile_name_label()
    test_bypass_es_boton_junto_al_mute()
    test_botones_de_escucha_mismo_ancho_y_sin_recortes()
    test_indicadores_vuelven_a_reposo_al_detener()
    test_dispositivo_perdido_detiene_y_avisa()
    test_boton_activo_letra_amarilla_y_negrita()
    test_mute_button_gating_and_state()
    test_bypass_remembers_output_gain()
    test_bypass_clears_status_bar_message()
    test_bypass_gain_persiste_entre_sesiones()
    test_update_button_and_skip()
    test_eibi_tab_search_and_no_network()
    test_translate_tab_warning_and_not_installed()
    test_translate_tab_show_mode()
    test_translate_tab_format_segment_sin_translated_no_crashea()
    test_translate_tab_clear_button()
    test_translate_tab_copy_to_clipboard()
    test_translate_tab_min_confidence_slider_persists()
    test_translate_tab_low_confidence_warning()
    test_translate_tab_music_notice_not_repeated()
    test_translate_tab_detected_lang_and_avg_latency()
    test_detener_procesamiento_detiene_traduccion()
    test_detener_procesamiento_no_rompe_si_traduccion_inactiva()
    test_about_dialog()
    test_about_donate_button()
    test_export_diagnostics_button()
    test_auto_load_respects_saved_mode()
    test_canceller_subcontrols_require_noise()
    test_supresor_tiene_un_indicador_por_etapa()
    test_umbral_de_trama_llega_a_la_zona_util()
    test_sliders_de_lambda_d_solo_en_adaptativo()
    test_bass_and_character_controls()
    test_agc_noise_ceiling_controls()
    test_voice_leveler_requires_noise()
    test_leveler_continuous_checkbox()
    test_bandpass_preset_combo()
    test_bandpass_preset_ambiguo_no_salta()
    test_bandpass_out_requires_post_and_independent()
    test_refresh_from_config_restores_checkboxes()
    test_window_title_reflects_preset()
    test_overwrite_clears_modified_in_title()
    test_export_import_preset_buttons()
    test_import_preset_name_collision_overwrite()
    test_advanced_change_marks_modified()
    test_waterfall_toggle_and_source()
    test_waterfall_diff_mode()
    test_waterfall_rgb_incremental()
    test_alternate_rows_dark_on_linux_style()
    test_incompatible_devices_disable_activate()
    test_noise_fall_slider()
    test_gate_threshold_slider_on_principal()
    test_mcra_en_bypass_no_es_falla()
    test_bypass_indicadores_en_reposo()
    test_noise_freeze_slider()
    test_all_sliders_have_tooltip()
    test_dsp_error_is_visible()
    test_mcra_stall_reason()
    test_ui_scale_combo()
    test_ui_scales_that_fit()
    test_read_ui_scale_tolerante()
    print()
    print("test_ui: OK")

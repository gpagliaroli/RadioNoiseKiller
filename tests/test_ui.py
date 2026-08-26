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

# Preset semilla en la carpeta temporal (test_window_title_reflects_preset lo usa).
PresetManager(presets_dir()).save("Voz natural - SSB", AppConfig())


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
    """7 pestanas en orden fijo, con 'Modulos' en la 2da posicion."""
    w = _win()
    tabs = w._tabs
    expected = [
        tr("Principal"), tr("Módulos"), tr("Avanzada Audio"),
        tr("Avanzada Impulsos"), tr("Avanzada Cancelador"),
        tr("Espectro"), tr("Presets"),
    ]
    got = [tabs.tabText(i) for i in range(tabs.count())]
    assert got == expected, f"Orden de pestanas inesperado: {got}"
    print("Orden de pestanas (7, Modulos en pos 1)   OK")


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
    dsp.squelch_enabled   = True
    dsp.presence_enabled  = False
    dsp.anf_enabled       = True
    w.refresh_from_config()
    _app.processEvents()

    assert w._chk_noise.isChecked() is True
    assert w._chk_exciter.isChecked() is False
    assert w._chk_squelch.isChecked() is True
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
    name = "Voz natural - SSB"
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


def test_mute_button_gating_and_state():
    """El boton Mute arranca deshabilitado (requiere proceso); al togglear
    llama set_output_mute y cambia texto/estilo; destogglear lo restaura."""
    w = _win()
    assert not w._btn_mute.isEnabled(), "Mute deberia arrancar deshabilitado (sin proceso)"

    calls = []
    orig = w._pipeline.set_output_mute
    w._pipeline.set_output_mute = lambda v: calls.append(v)
    try:
        w._btn_mute.setChecked(True)
        assert calls and calls[-1] is True, "toggle Mute no llamo set_output_mute(True)"
        assert w._btn_mute.styleSheet(), "Mute activo sin estilo de aviso"
        w._btn_mute.setChecked(False)
        assert calls[-1] is False, "destoggle Mute no llamo set_output_mute(False)"
        assert not w._btn_mute.styleSheet(), "Mute inactivo no limpio el estilo"
    finally:
        w._pipeline.set_output_mute = orig
    print("Mute: gating + estado del boton              OK")


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
    assert not w._check_bypass.isChecked(), "arranca sin bypass"
    init_bypass = w._out_gain_by_bypass[True]     # valor inicial (== config)

    # Ajuste en modo procesando → se recuerda en el slot False
    w._s_gain_out.set_value(-5.0, emit=True)
    assert w._out_gain_by_bypass[False] == -5.0, "no recordo la ganancia de procesando"

    # Pasar a bypass: el slider salta al valor guardado de bypass
    w._check_bypass.setChecked(True)
    assert abs(w._s_gain_out.value() - init_bypass) < 1e-6, "no restauro el valor de bypass"
    assert abs(w._pipeline._output_gain - 10 ** (init_bypass / 20.0)) < 1e-4, \
        "el pipeline no recibio la ganancia de bypass"

    # Ajuste distinto en bypass → se recuerda en el slot True
    w._s_gain_out.set_value(3.0, emit=True)
    assert w._out_gain_by_bypass[True] == 3.0, "no recordo la ganancia de bypass"

    # Volver a procesando: recupera -5.0; y de nuevo a bypass: recupera 3.0
    w._check_bypass.setChecked(False)
    assert abs(w._s_gain_out.value() - (-5.0)) < 1e-6, "no restauro el valor de procesando"
    w._check_bypass.setChecked(True)
    assert abs(w._s_gain_out.value() - 3.0) < 1e-6, "no recordo el valor de bypass en el 2do toggle"
    print("Bypass recuerda ganancia de salida (A/B)   OK")


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
        dsp_error_count = 0
        noise_has_profile = False
        db_in = -20.0
        noise_mode = "mcra"
        post_filter_extra_db = 0.0
        mcra_diag = "frames=0 warmup=80"
        volcados = []

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

    # Gating: es un control del cancelador, no debe quedar vivo sin el.
    w._config.dsp.noise_enabled = False
    tab.refresh_enabled_states()
    assert not row._slider.isEnabled(), "el slider queda activo sin el cancelador"
    w._config.dsp.noise_enabled = True
    tab.refresh_enabled_states()
    assert row._slider.isEnabled()

    w.close()
    print("slider del freno de caida del piso            OK")


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
    w._check_bypass.setChecked(False)
    w._s_gain_out.set_value(-5.0, emit=True)
    _app.processEvents()
    w._check_bypass.setChecked(True)
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
    w2._check_bypass.setChecked(True)
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
    test_mute_button_gating_and_state()
    test_bypass_remembers_output_gain()
    test_bypass_gain_persiste_entre_sesiones()
    test_about_dialog()
    test_about_donate_button()
    test_auto_load_respects_saved_mode()
    test_canceller_subcontrols_require_noise()
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
    test_advanced_change_marks_modified()
    test_waterfall_toggle_and_source()
    test_waterfall_diff_mode()
    test_incompatible_devices_disable_activate()
    test_noise_fall_slider()
    test_noise_freeze_slider()
    test_all_sliders_have_tooltip()
    test_dsp_error_is_visible()
    test_mcra_stall_reason()
    test_ui_scale_combo()
    test_ui_scales_that_fit()
    test_read_ui_scale_tolerante()
    print()
    print("test_ui: OK")

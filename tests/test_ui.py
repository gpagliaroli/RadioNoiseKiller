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

from config import AppConfig     # noqa: E402
from i18n import tr              # noqa: E402
from presets import PresetManager  # noqa: E402
from utils import presets_dir, settings_path  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

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
    """Techo de ruido del AGC: el slider sigue al checkbox y ambos llegan a config."""
    w = _win()
    aud = w._adv_audio_tab

    aud._chk_agc_ceiling.setChecked(False)
    _app.processEvents()
    assert not aud._s_agc_ceiling._slider.isEnabled(), "el slider deberia estar apagado"

    aud._chk_agc_ceiling.setChecked(True)
    _app.processEvents()
    assert aud._s_agc_ceiling._slider.isEnabled(), "el slider no se habilito"
    assert w._config.dsp.agc_noise_ceiling_enabled, "el checkbox no llego a la config"

    aud._s_agc_ceiling.set_value(-50.0, emit=True)
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
    (marcada = sin gate = música) y se gatea con el cancelador + nivelador."""
    w = _win()
    aud = w._adv_audio_tab

    # Gateada por el cancelador + nivelador (invariante 2)
    w._chk_noise.setChecked(True)
    w._chk_voice_leveler.setChecked(True)
    _app.processEvents()
    assert aud._chk_leveler_continuous.isEnabled(), "casilla deberia habilitarse"

    # Estado inicial conocido (settings.json de dev puede tener gate=False → casilla
    # ya marcada); sin esto setChecked(True) seria no-op y no dispararia la señal.
    aud._chk_leveler_continuous.blockSignals(True)
    aud._chk_leveler_continuous.setChecked(False)
    aud._chk_leveler_continuous.blockSignals(False)

    calls = []
    orig = w._pipeline.set_voice_leveler_gate_voice
    w._pipeline.set_voice_leveler_gate_voice = lambda g: calls.append(g)
    try:
        aud._chk_leveler_continuous.setChecked(True)   # continuo → SIN gate de voz
        assert calls[-1] is False, "continuo marcado deberia desactivar el gate (gate=False)"
        aud._chk_leveler_continuous.setChecked(False)  # gateado por voz
        assert calls[-1] is True, "continuo desmarcado deberia activar el gate (gate=True)"
    finally:
        w._pipeline.set_voice_leveler_gate_voice = orig

    w._chk_noise.setChecked(False)
    _app.processEvents()
    assert not aud._chk_leveler_continuous.isEnabled(), \
        "casilla habilitada sin cancelador (invariante 2)"
    print("Nivelador: casilla continuo + gating         OK")


def test_bandpass_sliders_gated_by_mode():
    """Los sliders de bandpass AM se habilitan solo en modo AM y los SSB solo en SSB
    (UX). El slider de orden es común a ambos. Cambiar el modo refresca el estado."""
    from config import RadioMode
    w = _win()
    aud = w._adv_audio_tab
    w._config.dsp.bandpass_pre_enabled = True   # asegurar bandpass activo

    _set_combo(w._combo_mode, RadioMode.AM)
    assert aud._s_am_lo._slider.isEnabled(),      "AM lo deshabilitado en modo AM"
    assert aud._s_am_hi._slider.isEnabled(),      "AM hi deshabilitado en modo AM"
    assert not aud._s_ssb_lo._slider.isEnabled(), "SSB lo habilitado en modo AM"
    assert aud._s_order._slider.isEnabled(),      "orden (común) deshabilitado"

    _set_combo(w._combo_mode, RadioMode.SSB)
    assert not aud._s_am_lo._slider.isEnabled(),  "AM lo habilitado en modo SSB"
    assert aud._s_ssb_lo._slider.isEnabled(),     "SSB lo deshabilitado en modo SSB"
    assert aud._s_ssb_hi._slider.isEnabled(),     "SSB hi deshabilitado en modo SSB"
    print("Bandpass AM/SSB gateado por modo           OK")


def test_bandpass_out_requires_post_and_independent():
    """Los sliders de salida independiente requieren bandpass post + la casilla."""
    from config import RadioMode
    w = _win()
    aud = w._adv_audio_tab
    _set_combo(w._combo_mode, RadioMode.AM)   # chequeamos los sliders de salida AM

    w._chk_bandpass_post.setChecked(True)
    aud._chk_bp_out.setChecked(True)
    _app.processEvents()
    assert aud._s_out_am_lo._slider.isEnabled(), "salida independiente deberia habilitarse"

    aud._chk_bp_out.setChecked(False)
    _app.processEvents()
    assert not aud._s_out_am_lo._slider.isEnabled(), \
        "salida independiente habilitada con la casilla OFF"

    aud._chk_bp_out.setChecked(True)
    w._chk_bandpass_post.setChecked(False)
    _app.processEvents()
    assert not aud._s_out_am_lo._slider.isEnabled(), \
        "salida independiente habilitada con bandpass post OFF"
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
    print("Cascada: toggle + fuente + push headless    OK")


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


if __name__ == "__main__":
    test_tab_order()
    test_modules_group_moved_to_own_tab()
    test_post_filter_on_principal_autoenable()
    test_profile_buttons_visibility_by_mode()
    test_loaded_profile_name_label()
    test_mute_button_gating_and_state()
    test_bypass_remembers_output_gain()
    test_about_dialog()
    test_auto_load_respects_saved_mode()
    test_canceller_subcontrols_require_noise()
    test_bass_and_character_controls()
    test_agc_noise_ceiling_controls()
    test_voice_leveler_requires_noise()
    test_leveler_continuous_checkbox()
    test_bandpass_sliders_gated_by_mode()
    test_bandpass_out_requires_post_and_independent()
    test_refresh_from_config_restores_checkboxes()
    test_window_title_reflects_preset()
    test_overwrite_clears_modified_in_title()
    test_advanced_change_marks_modified()
    test_waterfall_toggle_and_source()
    test_incompatible_devices_disable_activate()
    print()
    print("test_ui: OK")

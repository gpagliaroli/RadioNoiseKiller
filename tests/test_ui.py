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
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

_app = QApplication.instance() or QApplication([])

from i18n import tr          # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


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

def test_canceller_subcontrols_require_noise():
    """Invariante 2: los sub-modulos del cancelador no corren sin el cancelador.
    Con el cancelador OFF, sus sliders quedan deshabilitados aunque el
    sub-modulo este activo."""
    w = _win()
    can = w._adv_canceller_tab

    w._chk_noise.setChecked(True)
    w._chk_post_filter.setChecked(True)
    _app.processEvents()
    assert can._s_post_filter._slider.isEnabled(), "post-filtro deberia estar habilitado"

    w._chk_noise.setChecked(False)   # apagar SOLO el cancelador
    _app.processEvents()
    assert not can._s_post_filter._slider.isEnabled(), \
        "post-filtro habilitado con cancelador OFF (invariante 2)"
    print("Sub-controles del cancelador gateados      OK")


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


def test_agc_custom_sliders_gated():
    """Los sliders de AGC Custom solo se habilitan con el preset 'custom'."""
    w = _win()
    aud = w._adv_audio_tab

    _set_combo(w._combo_agc, "custom")
    assert aud._s_agc_target._slider.isEnabled(), "AGC target deberia habilitarse en custom"

    _set_combo(w._combo_agc, "fast")
    assert not aud._s_agc_target._slider.isEnabled(), \
        "AGC target habilitado sin preset custom"
    print("Sliders AGC Custom gateados                OK")


def test_bandpass_out_requires_post_and_independent():
    """Los sliders de salida independiente requieren bandpass post + la casilla."""
    w = _win()
    aud = w._adv_audio_tab

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


if __name__ == "__main__":
    test_tab_order()
    test_modules_group_moved_to_own_tab()
    test_profile_buttons_visibility_by_mode()
    test_canceller_subcontrols_require_noise()
    test_voice_leveler_requires_noise()
    test_agc_custom_sliders_gated()
    test_bandpass_out_requires_post_and_independent()
    test_refresh_from_config_restores_checkboxes()
    test_window_title_reflects_preset()
    print()
    print("test_ui: OK")

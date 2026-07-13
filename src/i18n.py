"""
i18n — traducción liviana por diccionario (español → inglés).

Decisión de diseño: NO se usa Qt Linguist / QTranslator. Con dos idiomas y
las strings fuente en español, un diccionario Python evita el toolchain
.ts/.qm (lupdate/lrelease), los datas extra en los .spec y deja la
traducción en un archivo editable directamente.

Uso:
    from i18n import tr
    label = QLabel(tr("Dispositivos de Audio"))

- El texto fuente (español) es la clave. Si falta en el diccionario, se
  devuelve tal cual — la app nunca rompe por una traducción faltante.
- Strings con valores dinámicos: la plantilla se traduce ANTES de formatear:
      tr("Latencia: {ms} ms").format(ms=latencia)
  (no usar f-strings en textos traducibles).
- El idioma se fija una sola vez al arrancar (set_language en main.py,
  leído de settings.json). Cambiarlo requiere reiniciar la app: la UI se
  construye una vez y no hay mecanismo de retraducción en vivo.

El diccionario vive en i18n_en.py (un dict plano ES→EN).
"""

_lang = "es"
_catalog: dict[str, str] = {}

LANGUAGES = {"es": "Español", "en": "English"}


def set_language(lang: str) -> None:
    """Fija el idioma global. Llamar UNA vez, antes de construir la UI."""
    global _lang, _catalog
    _lang = lang if lang in LANGUAGES else "es"
    if _lang == "en":
        from i18n_en import CATALOG
        _catalog = CATALOG
    else:
        _catalog = {}


def get_language() -> str:
    return _lang


def tr(text: str) -> str:
    """Devuelve la traducción de `text` al idioma activo (o `text` si no hay)."""
    return _catalog.get(text, text)

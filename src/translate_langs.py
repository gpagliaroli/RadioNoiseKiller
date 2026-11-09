"""
Nombres de idiomas en cada idioma de Destino de la Traducción, para el
indicador "Idioma detectado": con Destino = Español, Whisper detecta "zh" y se
muestra "Chino (zh)", no "中文" (que no le sirve a quien no lee chino).

Cubre los idiomas de Origen del combo y los que más se escuchan en onda corta
y Whisper puede detectar con Origen = Auto. Lo que no está muestra el código.
Sin Qt.
"""

# código -> (es, en, pt, fr, de)
_DSTS = ("es", "en", "pt", "fr", "de")
_TABLE = {
    "en": ("Inglés", "English", "Inglês", "Anglais", "Englisch"),
    "es": ("Español", "Spanish", "Espanhol", "Espagnol", "Spanisch"),
    "zh": ("Chino", "Chinese", "Chinês", "Chinois", "Chinesisch"),
    "ja": ("Japonés", "Japanese", "Japonês", "Japonais", "Japanisch"),
    "ko": ("Coreano", "Korean", "Coreano", "Coréen", "Koreanisch"),
    "ru": ("Ruso", "Russian", "Russo", "Russe", "Russisch"),
    "de": ("Alemán", "German", "Alemão", "Allemand", "Deutsch"),
    "fr": ("Francés", "French", "Francês", "Français", "Französisch"),
    "pt": ("Portugués", "Portuguese", "Português", "Portugais", "Portugiesisch"),
    "it": ("Italiano", "Italian", "Italiano", "Italien", "Italienisch"),
    "ar": ("Árabe", "Arabic", "Árabe", "Arabe", "Arabisch"),
    "uk": ("Ucraniano", "Ukrainian", "Ucraniano", "Ukrainien", "Ukrainisch"),
    "pl": ("Polaco", "Polish", "Polonês", "Polonais", "Polnisch"),
    "nl": ("Neerlandés", "Dutch", "Holandês", "Néerlandais", "Niederländisch"),
    "tr": ("Turco", "Turkish", "Turco", "Turc", "Türkisch"),
    "fa": ("Persa", "Persian", "Persa", "Persan", "Persisch"),
    "hi": ("Hindi", "Hindi", "Hindi", "Hindi", "Hindi"),
    "id": ("Indonesio", "Indonesian", "Indonésio", "Indonésien", "Indonesisch"),
    "vi": ("Vietnamita", "Vietnamese", "Vietnamita", "Vietnamien", "Vietnamesisch"),
    "th": ("Tailandés", "Thai", "Tailandês", "Thaï", "Thailändisch"),
    "ro": ("Rumano", "Romanian", "Romeno", "Roumain", "Rumänisch"),
    "el": ("Griego", "Greek", "Grego", "Grec", "Griechisch"),
    "he": ("Hebreo", "Hebrew", "Hebraico", "Hébreu", "Hebräisch"),
    "sv": ("Sueco", "Swedish", "Sueco", "Suédois", "Schwedisch"),
    "cs": ("Checo", "Czech", "Tcheco", "Tchèque", "Tschechisch"),
    "hu": ("Húngaro", "Hungarian", "Húngaro", "Hongrois", "Ungarisch"),
    "bn": ("Bengalí", "Bengali", "Bengali", "Bengali", "Bengalisch"),
    "ur": ("Urdu", "Urdu", "Urdu", "Ourdou", "Urdu"),
    "sw": ("Suajili", "Swahili", "Suaíli", "Swahili", "Suaheli"),
    "ta": ("Tamil", "Tamil", "Tâmil", "Tamoul", "Tamil"),
    "ms": ("Malayo", "Malay", "Malaio", "Malais", "Malaiisch"),
    "fi": ("Finés", "Finnish", "Finlandês", "Finnois", "Finnisch"),
    "no": ("Noruego", "Norwegian", "Norueguês", "Norvégien", "Norwegisch"),
    "da": ("Danés", "Danish", "Dinamarquês", "Danois", "Dänisch"),
    "ca": ("Catalán", "Catalan", "Catalão", "Catalan", "Katalanisch"),
    "tl": ("Tagalo", "Tagalog", "Tagalo", "Tagalog", "Tagalog"),
}

LANG_NAMES = {code: dict(zip(_DSTS, names)) for code, names in _TABLE.items()}


def lang_name(code: "str | None", dst: "str | None") -> str:
    """Nombre del idioma `code` en el idioma `dst`; si no hay, en inglés; si el
    idioma no está en la tabla, el código tal cual."""
    if not code:
        return ""
    names = LANG_NAMES.get(code)
    if names is None:
        return code
    return names.get(dst or "", names["en"])

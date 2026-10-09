"""Wrapper de argostranslate. Instala el par de idiomas pedido si falta
(primera vez, necesita red) y traduce texto."""
import argostranslate.package
import argostranslate.translate


class NoLanguagePairError(Exception):
    pass


class MtEngine:
    def __init__(self):
        self._installed_pairs: set[tuple[str, str]] = set()
        self._refresh_installed()

    def _refresh_installed(self) -> None:
        # OJO: iterar lang.translations_from (no translations_to) y leer
        # tr.to_lang.code. Bug real que costó una sesión de depuración:
        # lang.translations_to son las traducciones que llegan A lang, así
        # que ahí tr.to_lang ES lang — con esa combinación el set terminaba
        # lleno de auto-pares (en,en)/(zh,zh)/... y NUNCA un par cruzado
        # real, así que la rama "ya instalado" de ensure_pair/_install_direct
        # jamás se activaba. translations_from es al revés: lang es el
        # origen, tr.to_lang es el destino real de esa traducción.
        self._installed_pairs = {
            (lang.code, tr.to_lang.code)
            for lang in argostranslate.translate.get_installed_languages()
            for tr in lang.translations_from
        }

    def _install_direct(self, src: str, dst: str) -> bool:
        """Instala el paquete src->dst si existe en el índice. True si quedó
        instalado (ya estaba o se instaló ahora), False si ese par directo
        no existe."""
        if src == dst or (src, dst) in self._installed_pairs:
            return True
        pkgs = argostranslate.package.get_available_packages()
        pkg = next((p for p in pkgs if p.from_code == src and p.to_code == dst), None)
        if pkg is None:
            return False
        path = pkg.download()
        argostranslate.package.install_from_path(path)
        self._refresh_installed()
        return True

    def ensure_pair(self, src: str, dst: str) -> None:
        """Instala lo necesario para traducir src->dst. Si no hay paquete
        directo, instala src->en + en->dst: argostranslate compone la ruta
        solo una vez que get_installed_languages() se recalcula con los dos
        tramos presentes (ver el bloque de "Pivot through intermediate
        languages" en su propio código) — no hace falta combinarlo a mano,
        alcanza con que _install_direct refresque _installed_pairs después
        de cada instalación. Lanza NoLanguagePairError si ni el directo ni
        el pivote por inglés quedan disponibles."""
        if src == dst or (src, dst) in self._installed_pairs:
            return
        argostranslate.package.update_package_index()
        if self._install_direct(src, dst):
            return
        if "en" not in (src, dst):
            ok_a = self._install_direct(src, "en")
            ok_b = self._install_direct("en", dst)
            if ok_a and ok_b and (src, dst) in self._installed_pairs:
                return
        raise NoLanguagePairError(
            f"{src}->{dst} no está en el índice de argostranslate (ni pivoteando por inglés)")

    def translate(self, text: str, src: str, dst: str) -> str:
        if not text.strip() or src == dst:
            return text
        self.ensure_pair(src, dst)
        try:
            return argostranslate.translate.translate(text, src, dst)
        except AttributeError:
            # argostranslate.translate.translate() revienta con
            # "'NoneType' object has no attribute 'translate'" cuando
            # get_translation_from_codes no encuentra ruta — no debería
            # pasar tras ensure_pair(), pero si pasa que se vea como un
            # error entendible, no una excepción cruda en la UI.
            raise NoLanguagePairError(
                f"{src}->{dst}: no se encontró una ruta de traducción instalada")

"""
Identificador de compilación, visible en el título de la ventana.

El workflow de CI sobreescribe este archivo antes de empaquetar con el SHA
corto del commit y la fecha (ver .github/workflows/build-linux.yml). Para el
build local de release en Windows, actualizarlo a mano o via script antes de
correr PyInstaller. En desarrollo queda "dev".
"""
BUILD_ID = "dev"

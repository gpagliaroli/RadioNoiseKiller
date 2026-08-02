---
name: release
description: Cierra y publica una versión de RadioNoiseKiller — bumps, manual bilingüe, tests, builds Windows/Linux, tag y release en GitHub con assets. Usar cuando el usuario pida "cerrar la versión", "hacer el release" o "publicar vX.Y".
---

# Release de RadioNoiseKiller (vX.Y)

Proceso completo de cierre de versión, tal como se ejecutó en v1.4 y v1.5. Ejecutar los pasos
en orden; cada uno tiene su verificación. No publicar si algo falla.

## 0. Precondiciones (verificar ANTES de empezar)

- Todo el contenido de la versión está en `main`, commiteado y pusheado.
- **Cada feature/fix fue validado por el usuario en hardware real** (Windows multi-monitor,
  notebook Ubuntu/Wayland, interfaz USB según aplique — ver invariantes de empaquetado en
  CLAUDE.md). Si algo quedó sin validar, preguntarle al usuario antes de seguir.
- CLAUDE.md tiene la lista "Cambios vX.Y (pendiente de release)" completa — es la fuente de
  las notas del release.

## 1. Bump de versión (2 lugares)

- `src/main.py` → `app.setApplicationVersion("X.Y.0")`
- `src/ui/main_window.py` → `setWindowTitle(f"RadioNoiseKiller  vX.Y  ·  build {BUILD_ID}")`

## 2. Manual bilingüe

- `MANUAL.md` (ES): documentar los cambios de la versión y bump del número en encabezado
  (`**Versión X.Y**`) y pie (`*RadioNoiseKiller — versión X.Y*`).
- `MANUAL_EN.md` (EN): **reflejar exactamente los mismos cambios** — la sincronización es
  manual; terminología alineada con `src/i18n_en.py`.
- Generar ambos PDFs con `tools/gen_manual_pdf.py` (markdown2 + xhtml2pdf; weasyprint NO
  funciona en Windows). Correr desde la raíz:
  `.venv\Scripts\python.exe tools\gen_manual_pdf.py MANUAL.md    MANUAL_RadioNoiseKiller_vX.Y.pdf`
  y lo mismo con `MANUAL_EN.md` → `..._vX.Y_EN.pdf`. El script agrega portada con el logo
  (`Images/RNK_ico.png`) y resuelve el diagrama del pipeline. Los PDFs están gitignoreados.
- Si se cambió algún módulo del pipeline, regenerar el diagrama con
  `tools/gen_pipeline_diagram.py` (salidas versionadas en `Images/pipeline_diagram*.png`).
- Si se agregó, quitó o ajustó algún preset de fábrica, regenerar el paquete con
  `tools/gen_presets_zip.py` (`Presets/Presets.zip`, versionado — es lo que se le pasa al
  usuario final; el bundle no trae presets). El zip es determinista: si no cambió nada, no
  genera diff.
- Verificar con pypdf: cantidad de páginas y presencia de los términos nuevos en ambos.

## 3. Tests

`.venv\Scripts\python.exe tests\run_all.py` (o `test.cmd`) — corre las 8 suites de regresión
headless en subprocesos aislados, con `RNK_DATA_DIR` a un temp dir por suite (no tocan el
`settings.json` ni los `Presets/` reales). Todas en verde o no hay release.
`test_devices` / `test_hostapis` quedan fuera del runner: requieren hardware de audio y son
diagnósticos — correrlos a mano si el release tocó enumeración de dispositivos.

## 4. Commit de release + tag

- Actualizar CLAUDE.md: "Cambios vX.Y (pendiente de release)" → "**vX.Y publicada (mes año)**"
  con la nota del manual.
- Commit `release: vX.Y — <resumen>` (sin comillas dobles en el mensaje — el quoting de
  PowerShell 5.1 hacia git las rompe). Co-Authored-By de rigor.
- `git tag vX.Y && git push origin main vX.Y` — **el tag dispara el build Linux en CI**
  (`.github/workflows/build-linux.yml`).

## 5. Build Windows (local, en paralelo con el CI)

1. Estampar `src/buildinfo.py`: `BUILD_ID = "<hash-corto> <yyyy-MM-dd>"` (hash del commit de
   release).
2. `.venv\Scripts\python.exe -m PyInstaller reductor.spec --clean --noconfirm --distpath dist_vXY`
   (usar distpath propio: `dist/` puede estar bloqueado por una instancia corriendo).
3. **Restaurar buildinfo**: `git checkout -- src/buildinfo.py`.
4. Copiar AMBOS PDFs dentro de `dist_vXY/RadioNoiseKiller/`.
5. Zip: `RadioNoiseKiller_vX.Y.zip`.
6. Smoke test: lanzar el exe, confirmar vivo ~10 s, matar. (El título/ventana no son
   enumerables desde la sesión del agente — vivo alcanza; la verificación visual es del usuario.)

## 6. Build Linux (artifact del CI)

- Esperar el run del tag en verde (poll por API con el token de `git credential fill`).
- Descargar el artifact `RadioNoiseKiller-linux-x86_64`, renombrar a
  `RadioNoiseKiller_vX.Y-linux-x86_64.zip`.
- Si la versión tocó los specs o el recorte de Qt: verificar contenido del zip (plugins
  wayland presentes — ver invariantes de empaquetado en CLAUDE.md).

## 7. Release en GitHub

- **No hay `gh` instalado.** Usar la API REST con el token de
  `printf 'protocol=https\nhost=github.com\n\n' | git credential fill` (en bash; nunca
  imprimir el token).
- Crear release sobre el tag: nombre `RadioNoiseKiller vX.Y`, notas en español al estilo de
  v1.4/v1.5 (secciones por área, sección "Descargas" al final con instrucciones por plataforma;
  si hay cambios de idioma/manual, resumen breve en inglés).
- Assets: los dos zips + los dos PDFs sueltos.
- Verificar por API que los 4 assets queden `uploaded`, y pedirle al usuario un vistazo final
  al release en el navegador.

## 8. Cierre

- `git status` limpio (commitear `.claude/settings.local.json` si acumuló permisos).
- Confirmar al usuario: URL del release, tamaños de los assets, y qué validaciones de hardware
  quedaron hechas vs. pendientes.

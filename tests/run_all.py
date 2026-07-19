"""
Runner de todas las suites de regresión headless (sin hardware de audio).

Corre cada test en su propio subproceso (aislamiento) y muestra un resumen.
El test de UI corre con QT_QPA_PLATFORM=offscreen. Sale con código != 0 si
alguna suite falla — apto para CI o para correr a mano antes de commitear.

Uso:
    .venv\\Scripts\\python.exe tests\\run_all.py          (Windows)
    .venv/bin/python        tests/run_all.py             (Linux/Pi)

Se excluyen a propósito test_devices / test_hostapis (requieren hardware de
audio real y son diagnósticos, no de regresión).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# Suites deterministas, en orden de más rápida/básica a más integral.
SUITES = [
    "test_dsp",
    "test_presets",
    "test_noise_vad",
    "test_noise_profiles",
    "test_pipeline",
    "test_integration",
    "test_ui",          # requiere QT_QPA_PLATFORM=offscreen
]


def run_one(name: str) -> tuple[bool, float, str]:
    env = dict(os.environ)
    if name == "test_ui":
        env["QT_QPA_PLATFORM"] = "offscreen"
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, name + ".py")],
        env=env, capture_output=True, text=True,
    )
    dt = time.perf_counter() - t0
    ok = proc.returncode == 0
    return ok, dt, (proc.stdout + proc.stderr)


def main() -> int:
    print("=" * 60)
    print("  RadioNoiseKiller - suite de regresion")
    print("=" * 60)
    failed = []
    for name in SUITES:
        path = os.path.join(HERE, name + ".py")
        if not os.path.exists(path):
            print(f"  {name:<22} SKIP (no existe)")
            continue
        ok, dt, out = run_one(name)
        status = "PASS" if ok else "FAIL"
        print(f"  {name:<22} {status}  ({dt:4.1f}s)")
        if not ok:
            failed.append(name)
            # Mostrar las últimas líneas del fallo para diagnóstico rápido.
            tail = "\n".join(out.strip().splitlines()[-12:])
            print("  " + "-" * 40)
            for line in tail.splitlines():
                print("    " + line)
            print("  " + "-" * 40)
    print("=" * 60)
    if failed:
        print(f"  RESULTADO: {len(failed)} suite(s) con fallos: {', '.join(failed)}")
        return 1
    print("  RESULTADO: todas las suites pasaron  OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

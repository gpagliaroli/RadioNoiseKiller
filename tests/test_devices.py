import sys
sys.path.insert(0, "src")
from audio.devices import list_devices, get_default_input, get_default_output

devices = list_devices()
print(f"Dispositivos encontrados: {len(devices)}")
for d in devices:
    tags = []
    if d.supports_input():
        tags.append("IN")
    if d.supports_output():
        tags.append("OUT")
    label = "/".join(tags)
    print(f"  [{d.index:2d}] {label:6s} | {d.name}")

print()
inp = get_default_input()
out = get_default_output()
print(f"Default entrada: {inp}")
print(f"Default salida:  {out}")

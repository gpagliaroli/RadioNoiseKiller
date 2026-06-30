import sys
sys.path.insert(0, "src")
import sounddevice as sd

print("Host APIs disponibles:")
for i, api in enumerate(sd.query_hostapis()):
    print(f"  [{i}] {api['name']}")

print()
print("Dispositivos con su host API:")
for i, dev in enumerate(sd.query_devices()):
    api_name = sd.query_hostapis(dev["hostapi"])["name"]
    has_in  = dev["max_input_channels"] > 0
    has_out = dev["max_output_channels"] > 0
    if not has_in and not has_out:
        continue
    io = ("IN" if has_in else "  ") + ("/" if has_in and has_out else " ") + ("OUT" if has_out else "   ")
    print(f"  [{i:2d}] {io:7s} | {api_name:35s} | {dev['name']}")

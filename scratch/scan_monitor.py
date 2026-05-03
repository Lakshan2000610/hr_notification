with open("templates/monitor_devices.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "active" in line.lower() or "deactivate" in line.lower() or "status" in line.lower() or "update_device_status" in line.lower():
        print(f"Line {i+1}: {line.strip()}")

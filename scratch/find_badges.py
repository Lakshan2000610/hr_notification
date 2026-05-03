with open("templates/monitor_devices.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "status" in line and "badge" in line:
        print(f"Line {i+1}: {line.strip()}")

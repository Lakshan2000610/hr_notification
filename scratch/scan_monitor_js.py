with open("templates/monitor_devices.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i in range(495, 565):
    if i < len(lines):
        print(f"Line {i+1}: {lines[i].strip()}")

with open("templates/send_message.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "fetch(" in line or "alert" in line:
        print(f"Line {i+1}: {line.strip()}")

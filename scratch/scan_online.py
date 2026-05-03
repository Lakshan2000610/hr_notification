with open("app_sql.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "'online'" in line.lower() or '"online"' in line.lower():
        print(f"Line {i+1}: {line.strip()}")

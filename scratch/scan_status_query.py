with open("app_sql.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "where status = 1" in line.lower() or "where status=1" in line.lower():
        print(f"Line {i+1}: {line.strip()}")

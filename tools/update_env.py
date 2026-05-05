"""Usage: update_env.py <KEY> <VALUE>
Updates or inserts KEY=VALUE in .env at project root.
"""
import pathlib
import re
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: update_env.py <KEY> <VALUE>")

key = sys.argv[1]
value = sys.argv[2]
env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"

if not env_path.exists():
    sys.exit(f"ERROR: {env_path} not found")

text = env_path.read_text(encoding="utf-8")
pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
line = f"{key}={value}"

if pattern.search(text):
    text = pattern.sub(line, text)
else:
    text = text.rstrip() + "\n" + line + "\n"

env_path.write_text(text, encoding="utf-8")
print(f".env: {key} updated")

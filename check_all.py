import ast, pathlib, sys

ok, fail = 0, 0
for f in sorted(pathlib.Path(".").rglob("*.py")):
    if "archive" in str(f) or "__pycache__" in str(f) or "_backups" in str(f):
        continue
    size = f.stat().st_size
    try:
        ast.parse(f.read_text(encoding="utf-8"))
        if size < 100:
            print(f"  [WARN] {f}: {size:,} bytes (suspiciously small)")
            fail += 1
        else:
            ok += 1
    except SyntaxError as e:
        print(f"  [FAIL] {f}: {size:,} bytes - SyntaxError line {e.lineno}: {e.msg}")
        fail += 1

print(f"\nResults: {ok} OK, {fail} issues")
if fail == 0:
    print("All project Python files parse clean.")
else:
    print("ACTION REQUIRED: files above need inspection.")
    sys.exit(1)

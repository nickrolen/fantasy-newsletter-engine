"""
Every text file the engine opens names its encoding.

STATUS 10-12 sec.3 item 1: data_loader opened ROSTERS.json with open(f, "r")
and crashed under cp1252 the first time an accented name reached it -- the
2026-27 rosters came from the draft, which keeps Yahoo's "Nikola Jokić",
where every earlier ROSTERS.json came from LINEUPS, which strips accents.
Nine seasons of accidental safety. Python on Windows defaults to the locale
encoding; on Linux, where these tests also run, to UTF-8, so a plain
round-trip test would pass with the bug in place. EncodingWarning (-X
warn_default_encoding) is raised wherever an encoding was left to default,
on any platform, so the round trip below fails if one is.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _unencoded_opens(path: Path):
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(n, ast.Call):
            continue
        f, kws = n.func, {k.arg for k in n.keywords}
        if "encoding" in kws:
            continue
        if isinstance(f, ast.Name) and f.id == "open":
            mode = (n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant)
                    else next((k.value.value for k in n.keywords if k.arg == "mode"), "r"))
            if "b" not in str(mode):
                yield n.lineno
        elif isinstance(f, ast.Attribute) and f.attr in ("read_text", "write_text"):
            if (f.attr == "read_text" and not n.args) or (f.attr == "write_text" and len(n.args) < 2):
                yield n.lineno


def test_no_text_file_is_opened_without_an_encoding():
    offenders = [f"{p.relative_to(ROOT).as_posix()}:{line}"
                 for p in sorted((ROOT / "modules").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
                 for line in _unencoded_opens(p)]
    assert not offenders, f"open text files with encoding=\"utf-8\": {offenders}"


def test_an_accented_name_round_trips_through_the_roster_path(tmp_path):
    rosters = {"rosters": {"Hayden": ["Nikola Jokić", "Alperen Şengün"],
                           "Nick": ["Luka Dončić"]}}
    path = tmp_path / "ROSTERS.json"
    path.write_text(json.dumps(rosters, ensure_ascii=False), encoding="utf-8")
    probe = f"""
import json, sys
sys.path.insert(0, {str(ROOT)!r})
from modules.data_loader import load_json_file, _read_rosters_file
from modules.projections import load_rosters_from_config
p = {str(path)!r}
from pathlib import Path
a = load_json_file(Path(p))["rosters"]
b = _read_rosters_file(Path(p))
c = load_rosters_from_config(p)
assert a == b == c, (a, b, c)
# The line that crashed on 10-12: it reads the live config/ROSTERS.json,
# which since the draft holds accented names.
from modules.data_loader import FantasyData
FantasyData().get_current_rosters()
print(json.dumps(c["Hayden"]))
"""
    out = subprocess.run(
        [sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning",
         "-c", probe], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == ["Nikola Jokić", "Alperen Şengün"]

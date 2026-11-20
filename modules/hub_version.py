"""
hub_version.py -- which hub publishes (5a): config/league_config.json
hub.version, "v1" (the current page, modules/hub_page) or "v2" (the new hub,
modules/hub_v2). A REQUIRED key: missing, or anything but those two, raises.

    version()                -> "v1" | "v2", read from the engine's config each
                                call (a run sees the file as committed, not an
                                import-time copy)
    check_v2_whole(payload)  -> raises V2HubFailed when the new hub's keys or
                                the ratings failed (v2 only: soft under v1)

THE SWITCH, BOTH WAYS, IS THIS ONE KEY.
  v1: everything publishes exactly as before 5a, byte for byte. The new hub's
      payload keys are still built, softly (payload["v2_error"], the run's
      "ratings" block), and published nowhere.
  v2: every hub-building run (the nightly's step 9, build_hub.py) publishes
      the new hub to the same directory (output/hub_publish/), so the same
      URL, with the same passphrase and the same salt: a phone's remembered
      key keeps working. The new hub's soft failures become HARD: a payload
      whose v2 keys failed (v2_error) or whose ratings failed is refused, the
      run fails like any other hub failure (the failure issue opens) and the
      last good page stays up, because nothing is pushed.
  The old page's code stays in the repo, unused under v2, until Nick says to
  remove it. Switching back is the same one-line change; the content-keyed
  files (cards, headshots, issues) come back byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path

VERSIONS = ("v1", "v2")
CONFIG_RELPATH = Path("config") / "league_config.json"


class HubVersionError(RuntimeError):
    """hub.version is missing or not one of VERSIONS."""


class V2HubFailed(RuntimeError):
    """Under v2, a soft failure of the new hub's keys or the ratings: hard."""


def from_config(cfg: dict) -> str:
    hub = cfg.get("hub") if isinstance(cfg, dict) else None
    if not isinstance(hub, dict) or "version" not in hub:
        raise HubVersionError("config/league_config.json has no hub.version: it is required (\"v1\", the "
                              "current page, or \"v2\", the new hub)")
    v = hub["version"]
    if v not in VERSIONS:
        raise HubVersionError(f"config/league_config.json hub.version is {v!r}: it must be one of "
                              f"{', '.join(repr(x) for x in VERSIONS)}")
    return v


ENGINE_CONFIG = Path(__file__).resolve().parent.parent / CONFIG_RELPATH


def _config() -> dict:
    """The engine's config/league_config.json, read fresh (the file the rest
    of the engine reads, data_loader._LEAGUE_CONFIG, without its import-time
    copy). Tests replace this function."""
    if not ENGINE_CONFIG.is_file():
        raise HubVersionError(f"{CONFIG_RELPATH.as_posix()} is missing: hub.version is required")
    return json.loads(ENGINE_CONFIG.read_text(encoding="utf-8"))


def version(base_path=None, cfg: dict = None) -> str:
    """The hub that publishes: hub.version in cfg, else in the engine's
    config (base_path is accepted for the callers' symmetry and not read:
    the config is the engine's, like every other key)."""
    return from_config(_config() if cfg is None else cfg)


def v2_failures(payload: dict) -> list:
    """What failed softly in the new hub's keys: [] when whole. Each item a
    line naming the stage and the error."""
    out = []
    err = payload.get("v2_error")
    if payload.get("v2") is None:
        if err:
            out.append(f"the new hub's keys failed at {err.get('stage')}: {err.get('error')}")
        else:
            out.append("the payload has no new-hub keys (payload v2): rebuild it with this engine "
                       "(python scripts/build_hub_state.py)")
        return out
    if err:                                       # v2 present and an error: never expected, never ignored
        out.append(f"the new hub's keys report an error at {err.get('stage')}: {err.get('error')}")
    rt = (payload["v2"].get("ratings") or {})
    if rt.get("error"):
        out.append(f"the ratings failed: {rt['error']}")
    return out


def check_v2_whole(payload: dict) -> None:
    """Under v2: refuse a payload whose new-hub keys or ratings failed."""
    f = v2_failures(payload)
    if f:
        raise V2HubFailed("hub.version is \"v2\" and the new hub cannot publish whole: " + "; ".join(f)
                          + ". Nothing is published; the last good page stays up")

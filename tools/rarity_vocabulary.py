"""Refresh contracts/rarity_vocabulary.json from the games' own data.

    python tools/rarity_vocabulary.py            # report the diff
    python tools/rarity_vocabulary.py --write    # update the contract

WHY THIS EXISTS. `store.cross_grader.rarity_band` was wrong twice by guessing
with a regex over an open set of strings, and both times it guessed LOW: Art
Rares and Treasure Rares filed as ordinary rares, then One Piece `SR` and `SEC`
filed as base. A third instance was already waiting -- three of Riftbound's
seven rarities scored `base`, including `Overnumbered`, which is its chase
treatment.

The fix is not a better regex. It is reading each game's actual vocabulary and
asserting that every string in it maps to a named band. This script produces
the list; tests/test_rarity.py does the asserting.

WHAT IT WRITES. Distinct rarity STRINGS only -- no counts, no prices, no
populations, no card payloads. A vocabulary is not provider data, and keeping
counts out of it keeps that obviously true.

NETWORK. Clones the public repositories over HTTPS. `raw.githubusercontent.com`
and `github.com` are reachable from the sandbox even though most provider APIs
are not, which is the only reason this could be done here rather than deferred
to the runner.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(REPO, "contracts", "rarity_vocabulary.json")

# The apitcg per-game data repositories. `{game}-tcg-data`, one per game, with
# cards under cards/{language}/{set}.json.
SOURCES = {
    "riftbound": "riftbound-tcg-data",
    "one-piece": "one-piece-tcg-data",
    "pokemon": "pokemon-tcg-data",
    "gundam": "gundam-tcg-data",
    "digimon": "digimon-tcg-data",
    "union-arena": "union-arena-tcg-data",
    "dragon-ball-fusion": "dragon-ball-fusion-tcg-data",
    # star-wars-unlimited-tcg-data exists and is EMPTY. Listed so that its
    # emptiness is a recorded fact rather than an omission somebody re-checks.
    "star-wars-unlimited": "star-wars-unlimited-tcg-data",
}


def rarities_in(root) -> tuple:
    """(distinct rarity strings, whether any card carried none).

    Reads the top-level `rarity`, then `attributes.Rarity`. The raw repos put
    it at the top level; the API nests it under `attributes`. Both are handled
    because the same parser reads both shapes elsewhere.
    """
    found, missing = set(), False
    for path in sorted(pathlib.Path(root).rglob("*.json")):
        if "/cards/" not in str(path):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = data if isinstance(data, list) else (
            data.get("data") or data.get("cards") or [])
        for card in rows:
            if not isinstance(card, dict):
                continue
            rarity = card.get("rarity")
            if rarity in (None, ""):
                attributes = card.get("attributes")
                if isinstance(attributes, dict):
                    rarity = attributes.get("Rarity")
            if rarity in (None, ""):
                missing = True
            else:
                found.add(str(rarity))
    return sorted(found), missing


def collect(sources=SOURCES, workdir=None):
    workdir = workdir or tempfile.mkdtemp()
    games, failures = {}, {}
    for game, repo in sorted(sources.items()):
        target = os.path.join(workdir, repo)
        if not os.path.isdir(target):
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet",
                 f"https://github.com/apitcg/{repo}", target],
                capture_output=True, text=True)
            if result.returncode and not os.path.isdir(target):
                failures[game] = result.stderr.strip()[:200]
                continue
        values, missing = rarities_in(target)
        games[game] = {"rarities": values, "cards_with_no_rarity": missing}
    return games, failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    sys.path.insert(0, REPO)
    from ingest.rarity import unmapped                    # noqa: PLC0415

    games, failures = collect()
    with open(CONTRACT, encoding="utf-8") as handle:
        current = json.load(handle)

    key = {"riftbound": "riftbound", "one-piece": "optcg", "pokemon": "pkmn",
           "gundam": "gundam", "digimon": "digimon",
           "union-arena": "union-arena",
           "dragon-ball-fusion": "dragon-ball-fusion",
           "star-wars-unlimited": "star-wars-unlimited"}

    for game, entry in sorted(games.items()):
        was = set(current["games"].get(game, {}).get("rarities", []))
        now = set(entry["rarities"])
        added, gone = sorted(now - was), sorted(was - now)
        missing = unmapped(entry["rarities"], game=key.get(game))
        print(f"{game:22} {len(now):>3} distinct"
              + (f"  +{added}" if added else "")
              + (f"  -{gone}" if gone else "")
              + (f"  UNMAPPED {missing}" if missing else ""))
    for game, why in sorted(failures.items()):
        print(f"{game:22} COULD NOT READ: {why}")

    if args.write:
        current["games"] = games
        with open(CONTRACT, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"\nwrote {CONTRACT}")
    # An unmapped string is not a failure -- it is tracked as `unknown`. The
    # exit code reports it anyway so a scheduled refresh can be noticed.
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Which adapters exist, imported so that one broken module is one broken source.

WHY THIS FILE EXISTS. Run #4 exited in fifteen seconds having ingested nothing
and written no summary. The cause was a single line, and the shape of the
failure is the part worth fixing: **new, speculative code executed in the same
breath as four working providers, so it could stop them before they started.**

`ingest/sources.yml` already draws that distinction for absent keys -- a
deferred provider is a gap, an expected one is a failure. This applies the same
distinction to broken code. Each adapter module is imported independently and
on its own terms:

* import succeeds                     -> the class, as before
* import fails, source `unverified`   -> a gap with the traceback, run continues
* import fails, source expected       -> a failure, but the OTHER sources still
                                         run and the summary still renders

The last one is the important guarantee. A hard failure should fail the run --
it should not fail the run *silently and early*, before anything that could
explain it has had a chance to execute.

Nothing here imports an adapter at module scope. `load()` does the importing,
inside a try, and returns what it found alongside what it could not.
"""

from __future__ import annotations

import importlib
import traceback

# name -> (module, class). The module split is load-bearing, not cosmetic:
# ingest.catalog_sources holds the three adapters that have never reached their
# live service, so a syntax error or a bad import there is contained to them.
SPECS = (
    ("tcgapi",              "ingest.adapters", "TcgApiAdapter"),
    ("pokemonpricetracker", "ingest.adapters", "PokemonPriceTrackerAdapter"),
    ("apitcg",              "ingest.adapters", "ApiTcgAdapter"),
    ("pricecharting",       "ingest.adapters", "PriceChartingAdapter"),
    ("fx_alphavantage",     "ingest.adapters", "FxAlphaVantageAdapter"),
    ("tcgdex",              "ingest.catalog_sources", "TcgdexAdapter"),
    ("cryst",               "ingest.catalog_sources", "CrystAdapter"),
    ("wiki52poke",          "ingest.catalog_sources", "Poke52Adapter"),
)


def load(specs=SPECS):
    """(adapters, broken).

    `adapters` maps name -> class for everything that imported. `broken` maps
    name -> {"module", "error", "traceback"} for everything that did not.

    Catches BaseException deliberately. An adapter module doing something
    strange at import time -- a `SystemExit` from a misplaced argument parser,
    a recursion limit -- must still be one broken source rather than a dead
    run, and `except Exception` would let both of those through.
    """
    adapters, broken = {}, {}
    for name, module_path, class_name in specs:
        try:
            module = importlib.import_module(module_path)
            adapters[name] = getattr(module, class_name)
        except BaseException as exc:                       # noqa: BLE001
            if isinstance(exc, KeyboardInterrupt):
                raise
            broken[name] = {
                "module": module_path,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
    return adapters, broken


ADAPTERS, BROKEN_ADAPTERS = load()

# Tried in this order for a combo none of the commercial providers cover.
# Read from here rather than from ingest.catalog_sources so that importing the
# priority order cannot itself be the thing that fails.
CN_SOURCE_PRIORITY = ("tcgdex", "cryst", "wiki52poke")

# Every source this project knows about, whether or not its code loaded. The
# runner iterates THIS, not ADAPTERS -- otherwise a source that failed to
# import silently vanishes from the summary, which is the same disappearance
# the gap rows exist to prevent.
ALL_SOURCE_NAMES = tuple(name for name, _m, _c in SPECS)


def render_import_report(adapters=None, broken=None) -> str:
    adapters = ADAPTERS if adapters is None else adapters
    broken = BROKEN_ADAPTERS if broken is None else broken
    lines = [f"{name:22} {'ok' if name in adapters else 'BROKEN'}"
             for name in ALL_SOURCE_NAMES]
    for name, failure in sorted(broken.items()):
        lines += ["", f"--- {name} ({failure['module']}) ---",
                  failure["traceback"].rstrip()]
    return "\n".join(lines) + "\n"


def main(argv=None):
    """`python -m ingest.registry` -- every adapter module, imported or not.

    In Python rather than a shell heredoc in the workflow. Two of this
    project's failures have now been shell logic inside YAML that no test could
    reach (runs #4 and #7), and this file exists because of the first one.
    """
    report = render_import_report()
    print(report, end="")
    return 1 if BROKEN_ADAPTERS else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

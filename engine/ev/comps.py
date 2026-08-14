"""Whose slab the comps describe.

A route comparison prices the same card through different graders, and the
comps almost never come from all of them. A PSA 10 and a CGC 10 do not sell for
the same money -- so pricing a CGC submission against PSA 10 comps produces a
number that is useful for one question and misleading for another:

* **Useful**: "what does this ROUTE cost?" Holding the comps fixed is exactly
  how you isolate fees, freight and import charges from slab premium.
* **Misleading**: "which slab should I own?" That question needs comps from
  each grader, and holding them fixed answers it wrongly and confidently.

So this is a FLAG, not a refusal. Refusing would throw away the comparison that
the route work exists to support. Rendering it silently would let a route-cost
comparison be read as a slab choice, which is the mistake that actually costs
money.

Three states, because "we were not told" is not the same as "they match":

* ``match``    -- the comps are from the route's own grader.
* ``mismatch`` -- they are from a named different grader.
* ``unstated`` -- nobody said. Treated as a flag, not as a match: assuming a
  match is the silent default this repository keeps refusing to take.
"""

from __future__ import annotations

from typing import Optional

MATCH = "match"
MISMATCH = "mismatch"
UNSTATED = "unstated"


def comp_basis(route_grader: Optional[str], comps_grader: Optional[str],
               *, route: Optional[str] = None) -> dict:
    """Compare who graded the comps against who grades on this route."""
    route_grader = (route_grader or "").strip() or None
    comps_grader = (comps_grader or "").strip() or None

    if comps_grader is None:
        state = UNSTATED
        note = (
            "The comps do not say which grader's slabs they came from. A "
            f"{route_grader or 'graded'} 10 and another grader's 10 do not sell "
            "for the same money, so this is a route-cost comparison only and "
            "must not be read as a choice of slab.")
    elif route_grader and comps_grader.upper() != route_grader.upper():
        state = MISMATCH
        note = (
            f"Comps are {comps_grader} sales, priced against a {route_grader} "
            f"submission. Holding the comps fixed is how the ROUTE cost is "
            f"isolated -- fees, freight and import charges -- but a "
            f"{comps_grader} 10 and a {route_grader} 10 are different assets "
            f"with different premiums. Do not read this as a slab choice.")
    else:
        state = MATCH
        note = f"Comps are {comps_grader} sales against a {comps_grader} submission."

    return {
        "state": state,
        "comps_grader": comps_grader,
        "route_grader": route_grader,
        "route": route,
        # One boolean the UI can hang a badge on, true for BOTH mismatch and
        # unstated -- because both mean the same thing to a reader.
        "flag": state != MATCH,
        "note": note,
    }

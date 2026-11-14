"""Feature modules that sit on top of the core (spending and budgets next, the coach later).

A module is a package with a `router` and an optional `FEATURE_FLAG` setting name. Listing it in
MODULES is all it takes to switch it on; the core never imports a module directly.
"""

MODULES: list[str] = ["budgets"]

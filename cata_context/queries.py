"""Expansion-owned query entry point; extend here without changing the other release."""
from _cata_context_core.queries import Queries as BaseQueries

class Queries(BaseQueries):
    def __init__(self, path, max_age_ms=5000, clock=None, *, expected_build=15595):
        super().__init__(path, max_age_ms, clock, expected_build=expected_build)

"""Expansion-owned CLI over the common transport."""
from _cata_context_core.cli import handler_for, summary
from _cata_context_core.cli import main as core_main
from .queries import Queries

def main(argv=None):
    return core_main(argv, query_factory=Queries)

if __name__ == "__main__":
    raise SystemExit(main())

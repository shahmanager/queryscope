"""QueryScope — zero-API-cost natural-language to SQL."""

__all__ = ["Engine"]
__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "Engine":
        from .engine import Engine

        return Engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

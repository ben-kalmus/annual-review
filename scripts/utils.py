"""
Shared formatting utilities used across analyse_*.py scripts.
"""


def fmt_duration(days: float) -> str:
    """Format a duration: use minutes when under a day, days otherwise."""
    if days < 1:
        return f"{days * 24 * 60:.0f} min"
    return f"{days:.1f} days"


def fmt_int(n: int | float) -> str:
    return f"{n:,.0f}"


def pct(n: int | float, total: int | float) -> str:
    return f"{n / total * 100:.0f}%" if total else "0%"


def bar(ratio: float, width: int = 20) -> str:
    """Block bar scaled to `width` chars representing 100%."""
    filled = round(min(ratio, 1.0) * width)
    return "█" * filled + "░" * (width - filled)

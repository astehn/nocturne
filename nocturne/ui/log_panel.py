from __future__ import annotations


def format_log_entry(name, option, delta, dims=None) -> str:
    """Tight enough for one line in the 240 px activity box (spec §5)."""
    label = f"{name} ({option})" if option not in (None, "") else name
    if dims is not None:
        return f"{label} · {dims[0]}×{dims[1]}"
    if delta is None:
        return label
    return f"{label} · Δ{delta:.1f}%"

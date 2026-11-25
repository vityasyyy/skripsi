"""Public LaTeX formatting helpers shared by the live analysis."""

from __future__ import annotations


def tex_escape(value: object) -> str:
    """Escape one value for LaTeX text mode."""
    text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def format_num(value: float | None, digits: int = 3) -> str:
    """Format a number with a decimal comma, or ``--`` when absent."""
    if value is None:
        return "--"
    return f"{value:.{digits}f}".replace(".", ",")


def format_p(value: float | None) -> str:
    """Format a p-value for the thesis tables."""
    if value is None:
        return "--"
    if value < 0.001:
        return "$<0{,}001$"
    return f"{value:.3f}".replace(".", ",")


def format_interval(value: float | None, interval: list | None) -> str:
    """Format a point estimate and its optional confidence interval."""
    if value is None:
        return "--"
    if interval is None:
        return format_num(value)
    return f"{format_num(value)} [{format_num(interval[0])}; {format_num(interval[1])}]"


__all__ = ["format_interval", "format_num", "format_p", "tex_escape"]

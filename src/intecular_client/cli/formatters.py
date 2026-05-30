"""Unit formatting helpers for sensor readings.

Metric is the device's native unit; the ``us`` flag converts the three
readings that have a meaningful US customary equivalent.
"""

from __future__ import annotations


def fmt_temperature(celsius: float | None, us: bool) -> str:
    """Format a temperature, converting to Fahrenheit for US units."""
    if celsius is None:
        return "—"
    if us:
        return f"{celsius * 9 / 5 + 32:.1f} °F"
    return f"{celsius:.1f} °C"


def fmt_pressure(pascals: float | None, us: bool) -> str:
    """Format a pressure, converting Pa to inHg for US units."""
    if pascals is None:
        return "—"
    if us:
        return f"{pascals / 3386.389:.2f} inHg"
    return f"{pascals:.0f} Pa"


def fmt_distance(value: float | None, us: bool) -> str:
    """Format a radar distance, converting to inches for US units.

    The device's distance unit is undocumented; millimeters is assumed.
    """
    if value is None:
        return "—"
    if us:
        return f"{value / 25.4:.1f} in"
    return f"{value:.0f} mm"

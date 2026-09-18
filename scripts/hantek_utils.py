#!/usr/bin/env python3
"""Shared ADC-to-voltage and sample-rate helpers for the hanteker analysis scripts.

Time-axis conversion (`sample_rate_for`) is a verified, geometry-based
formula -- see CLAUDE.md "Sample rate - VERIFIED formula":
sample_rate = 100 / time_per_div_seconds.

Voltage conversion is NOT derivable from the protocol, but is pinned down
by a physical measurement (not curve-fitting): the display is +/-4
divisions, the offset control moves the trace by 25 button-presses per
division, and a signal starts clipping right at the button-press count that
implies a 256-count (8-bit) ADC range of 256/25 = 10.24 divisions -- i.e.
each division is exactly 25 raw counts, independent of channel/scale/probe.
See CLAUDE.md "Voltage calibration" for the derivation (an earlier
AWG-based curve fit was tried and abandoned -- too sensitive to
cable/connection noise to trust, see CLAUDE.md).
"""

# seconds per division for every --time-scale value hanteker_cli accepts
SECONDS_PER_DIV = {
    "ns5": 5e-9, "ns10": 1e-8, "ns20": 2e-8, "ns50": 5e-8, "ns100": 1e-7,
    "ns200": 2e-7, "ns500": 5e-7,
    "us1": 1e-6, "us2": 2e-6, "us5": 5e-6, "us10": 1e-5, "us20": 2e-5,
    "us50": 5e-5, "us100": 1e-4, "us200": 2e-4, "us500": 5e-4,
    "ms1": 1e-3, "ms2": 2e-3, "ms5": 5e-3, "ms10": 1e-2, "ms20": 2e-2,
    "ms50": 5e-2, "ms100": 1e-1, "ms200": 2e-1, "ms500": 5e-1,
    "s1": 1.0, "s2": 2.0, "s5": 5.0, "s10": 10.0, "s20": 20.0,
    "s50": 50.0, "s100": 100.0, "s200": 200.0, "s500": 500.0,
}

# volts per division for every --scale value hanteker_cli accepts
SCALE_VOLTS = {
    "mv10": 0.01, "mv20": 0.02, "mv50": 0.05, "mv100": 0.1, "mv200": 0.2, "mv500": 0.5,
    "v1": 1.0, "v2": 2.0, "v5": 5.0, "v10": 10.0,
}

# Physically measured via the offset button's step size, see module docstring
# and CLAUDE.md "Voltage calibration".
COUNTS_PER_DIV = 25.0
CENTER_CODE = 128.0  # 256/2, i.e. mid-code of the 8-bit ADC


def sample_rate_for(time_scale: str) -> float:
    return 100.0 / SECONDS_PER_DIV[time_scale]


def sample_interval_for(time_scale: str) -> float:
    return 1.0 / sample_rate_for(time_scale)


def volts_per_count_for(scale: str) -> float:
    return SCALE_VOLTS[scale] / COUNTS_PER_DIV


def raw_to_voltage(raw_byte: int, volts_per_count: float, center_code: float = CENTER_CODE) -> float:
    return (raw_byte - center_code) * volts_per_count


def raw_bytes_to_voltages(data: bytes, volts_per_count: float, center_code: float = CENTER_CODE):
    return [(b - center_code) * volts_per_count for b in data]

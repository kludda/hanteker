#!/usr/bin/env python3
"""Shared ADC-to-voltage and sample-rate helpers for the hanteker analysis scripts.

Time-axis conversion (`sample_rate_for`) is a verified, geometry-based
formula -- see AGENTS.md "Sample rate":
sample_rate = 100 / time_per_div_seconds.

Voltage conversion is NOT derivable from the protocol, but is pinned down
by a physical measurement (not curve-fitting): the display is +/-4
divisions, the offset control moves the trace by 25 button-presses per
division, and a signal starts clipping right at the button-press count that
implies a 256-count (8-bit) ADC range of 256/25 = 10.24 divisions -- i.e.
each division is exactly 25 raw counts, independent of channel/scale/probe.
See AGENTS.md "Voltage scale" for the derivation (an earlier
AWG-based curve fit was tried and abandoned -- too sensitive to
cable/connection noise to trust, see AGENTS.md).

Channel offset (`channel --offset <V>`) shifts what the raw code range
means, not just where the trace sits on screen -- verified empirically:
applying `--offset 1.0` at `--scale v1` (volts_per_count=0.04) shifted the
measured center by +25.1 raw counts, matching `1.0V / 0.04 = 25` counts
exactly. So `voltage = (raw_byte - 128) * volts_per_count - offset_volts`.

`sample_rate_for` warns on stderr when the formula implies a rate above
the datasheet's dual-channel ADC cap (125 MSa/s; 250 MSa/s single-channel)
-- at ns5..ns200 the device almost
certainly isn't literally converting that fast (see AGENTS.md "Sample rate" and "Datasheet" for why this
is flagged rather than corrected: it couldn't be conclusively verified
with the AWG available, which tops out at 25 MHz, far below the ~125 MHz
Nyquist a 250 MSa/s cap implies).
"""
import sys

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
# and AGENTS.md "Voltage scale".
COUNTS_PER_DIV = 25.0
CENTER_CODE = 128.0  # 256/2, i.e. mid-code of the 8-bit ADC

# Datasheet-rated ADC sampling rate caps, see AGENTS.md "Datasheet":
# 250 MSa/s with one channel enabled, 125 MSa/s with both. Whether
# the other channel is enabled can't be read back from the device, so the
# warning uses the lower (dual-channel) cap. The 100/time_per_div formula
# exceeds it at ns5..ns500 -- not corrected, just flagged.
MAX_SAMPLE_RATE_SINGLE = 250e6
MAX_SAMPLE_RATE_DUAL = 125e6


def sample_rate_for(time_scale: str, warn: bool = True) -> float:
    rate = 100.0 / SECONDS_PER_DIV[time_scale]
    if warn and rate > MAX_SAMPLE_RATE_DUAL:
        print(f"warning: --time-scale {time_scale} implies {rate:,.0f} Sa/s via the "
              f"100/time_per_div formula, above the datasheet's ADC cap "
              f"({MAX_SAMPLE_RATE_DUAL:,.0f} Sa/s with both channels enabled, "
              f"{MAX_SAMPLE_RATE_SINGLE:,.0f} Sa/s with one) -- real sample rate at this "
              f"timescale is unverified (device likely interpolates, (sin x)/x per "
              f"datasheet), see AGENTS.md 'Sample rate'",
              file=sys.stderr)
    return rate


def sample_interval_for(time_scale: str, warn: bool = True) -> float:
    return 1.0 / sample_rate_for(time_scale, warn=warn)


def volts_per_count_for(scale: str) -> float:
    return SCALE_VOLTS[scale] / COUNTS_PER_DIV


def raw_to_voltage(raw_byte: int, volts_per_count: float, center_code: float = CENTER_CODE,
                    offset: float = 0.0) -> float:
    return (raw_byte - center_code) * volts_per_count - offset

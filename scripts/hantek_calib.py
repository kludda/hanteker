#!/usr/bin/env python3
"""Shared ADC-to-voltage and sample-rate helpers for the hanteker analysis scripts.

Time-axis conversion (`sample_rate_for`) is a verified, geometry-based
formula that needs no calibration file -- see CLAUDE.md "Sample rate -
VERIFIED formula": sample_rate = 100 / time_per_div_seconds.

Voltage conversion depends on the physical channel, probe, and --scale, and
is NOT derivable from the protocol -- it's measured empirically by
`calibrate.py` (feeding the device's own AWG into a channel) and stored in
calibration.json next to this file. If no calibration is available for a
requested channel/scale, `voltage_scale_for` extrapolates from that
channel's fitted counts_per_div, or from DEFAULT_COUNTS_PER_DIV as a last
resort -- see CLAUDE.md "Voltage calibration" for the reasoning behind that
number and its ~5% uncertainty.
"""
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CALIBRATION_FILE = SCRIPT_DIR / "calibration.json"

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

# Last-resort defaults, used only when a channel has no calibration at all.
DEFAULT_COUNTS_PER_DIV = 24.0  # this project's best current estimate, see CLAUDE.md
DEFAULT_VOLTS_PER_COUNT = 4.0 / 102  # single external-signal measurement at v1/x1, see CLAUDE.md
DEFAULT_CENTER_CODE = 127.5  # theoretical 8-bit ADC midpoint


def sample_rate_for(time_scale: str) -> float:
    return 100.0 / SECONDS_PER_DIV[time_scale]


def sample_interval_for(time_scale: str) -> float:
    return 1.0 / sample_rate_for(time_scale)


def load_calibration(path=None) -> dict:
    path = Path(path) if path else DEFAULT_CALIBRATION_FILE
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_calibration(calibration: dict, path=None) -> None:
    path = Path(path) if path else DEFAULT_CALIBRATION_FILE
    with open(path, "w") as f:
        json.dump(calibration, f, indent=2)


def voltage_scale_for(channel, scale: str, calibration: dict, warn: bool = True):
    """Return (volts_per_count, center_code) for the given channel/--scale.

    Looks up an exact match from calibration.json first, then falls back to
    that channel's fitted counts_per_div (extrapolating volts_per_count =
    SCALE_VOLTS[scale] / counts_per_div), then to DEFAULT_COUNTS_PER_DIV.
    """
    chan = calibration.get(str(channel), {})
    scales = chan.get("scales", {})
    center = chan.get("adc_center") or DEFAULT_CENTER_CODE

    if scale in scales:
        return scales[scale]["volts_per_count"], center

    if "counts_per_div_fit" in chan:
        counts_per_div = chan["counts_per_div_fit"]
        source = f"channel {channel}'s fitted counts_per_div"
    else:
        counts_per_div = DEFAULT_COUNTS_PER_DIV
        source = "uncalibrated default counts_per_div"

    if warn:
        print(f"warning: no calibration for channel {channel} scale {scale!r}, "
              f"extrapolating from {source} ({counts_per_div:.2f} counts/div)",
              file=sys.stderr)

    return SCALE_VOLTS[scale] / counts_per_div, center


def raw_to_voltage(raw_byte: int, volts_per_count: float, center_code: float) -> float:
    return (raw_byte - center_code) * volts_per_count


def raw_bytes_to_voltages(data: bytes, volts_per_count: float, center_code: float):
    return [(b - center_code) * volts_per_count for b in data]

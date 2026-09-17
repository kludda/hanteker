#!/usr/bin/env python3
"""Convert a raw hanteker_cli `capture` byte-stream into a CSV of time,voltage.

Calibration is NOT read from the device or documented anywhere in this
protocol -- hanteker_cli only forwards raw 8-bit ADC counts.

Sample rate: verified empirically against the device's own AWG (exact known
frequencies), by counting periods captured at several --time-scale settings:

    time-scale   samples   periods   => sample rate
    us100        1000      2         => 1.000 MSa/s
    us100        2000      4         => 1.000 MSa/s
    us50         1000      1         => 2.000 MSa/s
    us5          1000      1         => 20.00 MSa/s
    us2          1000      1         => 50.00 MSa/s
    us1          1000      1         => 100.0 MSa/s

Every one of these matches, exactly, the formula:

    sample_rate_Sa_per_s = 100 / time_per_div_seconds

i.e. the device always samples at whatever rate makes 1000 samples span
exactly 10 divisions -- a fixed 100-samples/div design, independent of how
many total samples you actually request. Verified across a 100x range
(1us/div to 100us/div) with zero deviation at each point, so it's treated
as exact for that whole range below. Not verified outside ns5..s500 -- pass
--sample-interval directly to override if a timebase misbehaves.

An earlier attempt to calibrate this against an external signal generator
(unknown precision) gave noisy, non-matching results (e.g. ~12.4 MSa/s
measured vs 20 MSa/s from this formula at us5/div) -- that was generator
error, not a real hardware ceiling. Trust the AWG-based formula.

Voltage calibration is separate and still only empirically derived (not
verified against the AWG): from a measured 102-count Vpp of a known 4Vpp
external signal at 1V/div. Only valid at that vertical scale/probe factor;
override --volts-per-count and --center-code if you change either.
"""
import argparse
import csv
import sys

DEFAULT_VOLTS_PER_COUNT = 4.0 / 102   # from measured 102-count Vpp of a known 4Vpp signal at 1V/div
DEFAULT_CENTER_CODE = 127.5           # theoretical 8-bit ADC midpoint

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


def sample_interval_for(time_scale: str) -> float:
    seconds_per_div = SECONDS_PER_DIV[time_scale]
    sample_rate = 100.0 / seconds_per_div
    return 1.0 / sample_rate


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="raw .bin capture file (or - for stdin)")
    parser.add_argument("output", help="output .csv file (or - for stdout)")
    parser.add_argument("--time-scale", choices=sorted(SECONDS_PER_DIV),
                         help="the --time-scale the capture was taken at; "
                              "derives --sample-interval via the verified formula")
    parser.add_argument("--sample-interval", type=float,
                         help="seconds per sample; overrides --time-scale if both given")
    parser.add_argument("--volts-per-count", type=float, default=DEFAULT_VOLTS_PER_COUNT)
    parser.add_argument("--center-code", type=float, default=DEFAULT_CENTER_CODE)
    args = parser.parse_args()

    if args.sample_interval is not None:
        sample_interval = args.sample_interval
    elif args.time_scale is not None:
        sample_interval = sample_interval_for(args.time_scale)
    else:
        parser.error("must pass either --time-scale or --sample-interval")

    data = sys.stdin.buffer.read() if args.input == "-" else open(args.input, "rb").read()
    out = sys.stdout if args.output == "-" else open(args.output, "w", newline="")

    writer = csv.writer(out)
    writer.writerow(["sample_index", "time_s", "raw_value", "voltage"])
    for i, b in enumerate(data):
        t = i * sample_interval
        v = (b - args.center_code) * args.volts_per_count
        writer.writerow([i, f"{t:.9e}", b, f"{v:.4f}"])

    if out is not sys.stdout:
        out.close()


if __name__ == "__main__":
    main()

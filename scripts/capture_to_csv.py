#!/usr/bin/env python3
"""Convert a raw hanteker_cli `capture` byte-stream into a CSV of time,voltage.

Calibration is NOT read from the device or documented anywhere in this
protocol -- hanteker_cli only forwards raw 8-bit ADC counts.

Sample rate uses the verified geometry-based formula (see CLAUDE.md "Sample
rate - VERIFIED formula" and hantek_utils.py): sample_rate = 100 /
time_per_div_seconds.

Voltage conversion uses the physically-measured 25 counts/div, 128
center-code formula (see hantek_utils.py and CLAUDE.md "Voltage
calibration"). Pass --scale (matching what the capture was actually taken
with) to get the right volts/count for that vertical range; without it,
v1 is assumed. Pass --offset too if the channel wasn't at offset 0.
--volts-per-count/--center-code override the derived values directly.
"""
import argparse
import csv
import sys

import hantek_utils as hu


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="raw .bin capture file (or - for stdin)")
    parser.add_argument("output", help="output .csv file (or - for stdout)")
    parser.add_argument("--time-scale", choices=sorted(hu.SECONDS_PER_DIV),
                         help="the --time-scale the capture was taken at; "
                              "derives --sample-interval via the verified formula")
    parser.add_argument("--sample-interval", type=float,
                         help="seconds per sample; overrides --time-scale if both given")
    parser.add_argument("--scale", choices=sorted(hu.SCALE_VOLTS), default="v1",
                         help="the --scale the capture was taken at (default: v1)")
    parser.add_argument("--offset", type=float, default=0.0,
                         help="the channel --offset (volts) the capture was taken at (default: 0)")
    parser.add_argument("--volts-per-count", type=float, default=None,
                         help="override the derived value")
    parser.add_argument("--center-code", type=float, default=None,
                         help="override the derived value")
    args = parser.parse_args()

    if args.sample_interval is not None:
        sample_interval = args.sample_interval
    elif args.time_scale is not None:
        sample_interval = hu.sample_interval_for(args.time_scale)
    else:
        parser.error("must pass either --time-scale or --sample-interval")

    volts_per_count = args.volts_per_count
    if volts_per_count is None:
        volts_per_count = hu.volts_per_count_for(args.scale)
    center_code = args.center_code if args.center_code is not None else hu.CENTER_CODE

    data = sys.stdin.buffer.read() if args.input == "-" else open(args.input, "rb").read()
    out = sys.stdout if args.output == "-" else open(args.output, "w", newline="")

    writer = csv.writer(out)
    writer.writerow(["sample_index", "time_s", "raw_value", "voltage"])
    for i, b in enumerate(data):
        t = i * sample_interval
        v = hu.raw_to_voltage(b, volts_per_count, center_code, args.offset)
        writer.writerow([i, f"{t:.9e}", b, f"{v:.4f}"])

    if out is not sys.stdout:
        out.close()


if __name__ == "__main__":
    main()

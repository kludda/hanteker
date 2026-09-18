#!/usr/bin/env python3
"""Convert a raw hanteker_cli `capture` byte-stream into a CSV of time,voltage.

Calibration is NOT read from the device or documented anywhere in this
protocol -- hanteker_cli only forwards raw 8-bit ADC counts.

Sample rate uses the verified geometry-based formula (see CLAUDE.md "Sample
rate - VERIFIED formula" and hantek_calib.py): sample_rate = 100 /
time_per_div_seconds.

Voltage conversion defaults to the physically-measured 25 counts/div, 128
center-code formula (see hantek_calib.py and CLAUDE.md "Voltage
calibration"). Pass --channel and --scale (matching what the capture was
actually taken with) to check for a calibration.json override for that
exact channel/scale instead. --volts-per-count/--center-code override
either.
"""
import argparse
import csv
import sys

import hantek_calib as hc


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="raw .bin capture file (or - for stdin)")
    parser.add_argument("output", help="output .csv file (or - for stdout)")
    parser.add_argument("--time-scale", choices=sorted(hc.SECONDS_PER_DIV),
                         help="the --time-scale the capture was taken at; "
                              "derives --sample-interval via the verified formula")
    parser.add_argument("--sample-interval", type=float,
                         help="seconds per sample; overrides --time-scale if both given")
    parser.add_argument("--channel", type=int, choices=[1, 2],
                         help="the channel the capture was taken on; looks up voltage "
                              "calibration together with --scale")
    parser.add_argument("--scale", choices=sorted(hc.SCALE_VOLTS),
                         help="the --scale the capture was taken at; looks up voltage "
                              "calibration together with --channel")
    parser.add_argument("--calibration-file", default=None,
                         help=f"calibration.json to read (default: {hc.DEFAULT_CALIBRATION_FILE})")
    parser.add_argument("--volts-per-count", type=float, default=None,
                         help="override the calibrated/derived value")
    parser.add_argument("--center-code", type=float, default=None,
                         help="override the calibrated/derived value")
    args = parser.parse_args()

    if args.sample_interval is not None:
        sample_interval = args.sample_interval
    elif args.time_scale is not None:
        sample_interval = hc.sample_interval_for(args.time_scale)
    else:
        parser.error("must pass either --time-scale or --sample-interval")

    if (args.channel is None) != (args.scale is None):
        parser.error("--channel and --scale must be given together")

    if args.channel is not None:
        calibration = hc.load_calibration(args.calibration_file)
        volts_per_count, center_code = hc.voltage_scale_for(args.channel, args.scale, calibration)
    else:
        volts_per_count, center_code = hc.DEFAULT_VOLTS_PER_COUNT, hc.DEFAULT_CENTER_CODE

    if args.volts_per_count is not None:
        volts_per_count = args.volts_per_count
    if args.center_code is not None:
        center_code = args.center_code

    data = sys.stdin.buffer.read() if args.input == "-" else open(args.input, "rb").read()
    out = sys.stdout if args.output == "-" else open(args.output, "w", newline="")

    writer = csv.writer(out)
    writer.writerow(["sample_index", "time_s", "raw_value", "voltage"])
    for i, b in enumerate(data):
        t = i * sample_interval
        v = hc.raw_to_voltage(b, volts_per_count, center_code)
        writer.writerow([i, f"{t:.9e}", b, f"{v:.4f}"])

    if out is not sys.stdout:
        out.close()


if __name__ == "__main__":
    main()

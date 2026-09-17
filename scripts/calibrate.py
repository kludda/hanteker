#!/usr/bin/env python3
"""Calibrate a hanteker channel's voltage scaling against the device's own AWG.

The device has no documented/exposed self-calibration output, so this
reproduces the manual AWG-based method from CLAUDE.md's "Voltage
calibration" section: feed a known square wave from the AWG into ONE
channel (you must physically connect the AWG output to that channel's
probe -- move the cable and rerun this script to do the other channel),
sweep --amplitude at each --scale, and fit the resulting peak-to-peak ADC
counts to derive volts_per_count.

Assumes --probe x1, DC coupling, offset 0 on the measured channel. Results
are merged into calibration.json (default: next to this script) under the
given channel, so calibrating CH1 then CH2 doesn't clobber each other.

Only one process can hold the USB device -- close hanteker_gui first.
"""
import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

import hantek_calib as hc

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CLI = SCRIPT_DIR.parent / "target" / "release" / "hanteker_cli"

# Known-safe single-call size, see CLAUDE.md "Known single-call --capture-chunk sizes".
DEFAULT_CAPTURE_CHUNK = 4096
# Samples to drop off each end, see CLAUDE.md "Capture buffer contamination".
DEFAULT_TRIM = 600
DEFAULT_SETTLE = 2.0  # seconds to let the --scale relay finish switching
DEFAULT_SCALES = ["mv500", "v1", "v2", "v5"]  # smaller scales clip, v10 is too coarse to fit well
DEFAULT_AMPLITUDES = [0.5, 1.0, 1.5, 2.0, 2.5]
DEFAULT_FREQUENCY = 1000.0
MAX_AMPLITUDE = 2.5  # device limit


def check_gui_not_running():
    try:
        result = subprocess.run(["pgrep", "-f", "hanteker_gui"], capture_output=True)
    except FileNotFoundError:
        return  # no pgrep available, skip the check
    if result.returncode == 0 and result.stdout.strip():
        sys.exit("error: hanteker_gui appears to be running and may hold the USB "
                  "device. Close it first.")


def run_cli(cli, *args):
    result = subprocess.run([str(cli), *args], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"hanteker_cli {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def capture(cli, channel, capture_chunk):
    return run_cli(cli, "capture", "-c", str(channel), "-n", "1",
                    "--capture-chunk", str(capture_chunk))


def plateau_pp(raw: bytes, trim: int):
    """Robust low/high plateau means, ignoring head/tail capture contamination."""
    vals = list(raw)[trim:-trim]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    mid = (lo + hi) / 2
    low_vals = [v for v in vals if v <= mid]
    high_vals = [v for v in vals if v > mid]
    if not low_vals or not high_vals:
        return None
    low_mean = sum(low_vals) / len(low_vals)
    high_mean = sum(high_vals) / len(high_vals)
    clipped = lo == 0 or hi == 255
    return low_mean, high_mean, clipped


def fit_through_origin(xs, ys):
    """Least-squares slope for y = k*x (forced through the origin)."""
    sxx = sum(x * x for x in xs)
    if not sxx:
        return None
    return sum(x * y for x, y in zip(xs, ys)) / sxx


def calibrate_channel(cli, channel, scales, amplitudes, frequency, capture_chunk, trim, settle):
    print(f"Setting up CH{channel}: scope mode, {frequency:.0f} Hz square wave...")
    run_cli(cli, "device", "-m", "scope", "--start")
    run_cli(cli, "channel", "-c", str(channel), "--enable", "--coupling", "dc",
            "--probe", "x1", "--offset", "0")
    run_cli(cli, "awg", "--type", "square", "--frequency", str(frequency),
            "--offset", "0", "--start")

    scale_results = {}
    centers = []

    try:
        for scale in scales:
            run_cli(cli, "channel", "-c", str(channel), "--scale", scale)
            time.sleep(settle)

            points = []
            clipped_any = False
            for amplitude in amplitudes:
                run_cli(cli, "awg", "--amplitude", str(amplitude))
                time.sleep(0.3)
                raw = capture(cli, channel, capture_chunk)
                plateau = plateau_pp(raw, trim)
                if plateau is None:
                    print(f"  scale={scale} amplitude={amplitude}: capture unusable, skipping")
                    continue
                low_mean, high_mean, clipped = plateau
                pp = high_mean - low_mean
                centers.append((low_mean + high_mean) / 2)
                if clipped:
                    clipped_any = True
                    print(f"  scale={scale} amplitude={amplitude}: CLIPPED (pp={pp:.1f}), skipping")
                    continue
                points.append((amplitude, pp))
                print(f"  scale={scale} amplitude={amplitude}: pp={pp:.2f} counts")

            if len(points) < 2:
                print(f"  scale={scale}: not enough clean points, skipping")
                continue

            # counts_pp = k * amplitude; Vpp = 2*amplitude (AWG amplitude is a peak value,
            # see CLAUDE.md) => volts_per_count = 2/k
            k = fit_through_origin([a for a, _ in points], [pp for _, pp in points])
            if not k:
                print(f"  scale={scale}: fit failed, skipping")
                continue
            volts_per_count = 2.0 / k
            counts_per_div = hc.SCALE_VOLTS[scale] / volts_per_count
            scale_results[scale] = {
                "volts_per_count": volts_per_count,
                "counts_per_div": counts_per_div,
                "points": points,
                "clipped": clipped_any,
            }
            print(f"  scale={scale}: volts_per_count={volts_per_count:.5f} "
                  f"(counts_per_div={counts_per_div:.2f})")
    finally:
        run_cli(cli, "awg", "--stop")

    adc_center = statistics.mean(centers) if centers else None
    counts_per_div_values = [v["counts_per_div"] for v in scale_results.values()]
    counts_per_div_fit = statistics.mean(counts_per_div_values) if counts_per_div_values else None

    return {
        "probe": "x1",
        "awg_frequency_hz": frequency,
        "adc_center": adc_center,
        "scales": scale_results,
        "counts_per_div_fit": counts_per_div_fit,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("channel", type=int, choices=[1, 2],
                         help="which channel the AWG is physically connected to right now")
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI,
                         help=f"path to the hanteker_cli binary (default: {DEFAULT_CLI})")
    parser.add_argument("--out", type=Path, default=hc.DEFAULT_CALIBRATION_FILE,
                         help=f"calibration.json to update (default: {hc.DEFAULT_CALIBRATION_FILE})")
    parser.add_argument("--scales", default=",".join(DEFAULT_SCALES),
                         help="comma-separated --scale values to calibrate")
    parser.add_argument("--amplitudes", default=",".join(str(a) for a in DEFAULT_AMPLITUDES),
                         help="comma-separated AWG amplitudes (volts) to sweep")
    parser.add_argument("--frequency", type=float, default=DEFAULT_FREQUENCY,
                         help="AWG square-wave frequency in Hz")
    parser.add_argument("--capture-chunk", type=int, default=DEFAULT_CAPTURE_CHUNK,
                         help="samples per capture call -- stay at known-safe sizes, see CLAUDE.md")
    parser.add_argument("--trim", type=int, default=DEFAULT_TRIM,
                         help="samples to drop off each end of a capture before analyzing")
    parser.add_argument("--settle", type=float, default=DEFAULT_SETTLE,
                         help="seconds to wait after changing --scale before capturing")
    args = parser.parse_args()

    scales = [s.strip() for s in args.scales.split(",") if s.strip()]
    for s in scales:
        if s not in hc.SCALE_VOLTS:
            parser.error(f"unknown --scale value {s!r}, choices: {sorted(hc.SCALE_VOLTS)}")

    amplitudes = [float(a.strip()) for a in args.amplitudes.split(",") if a.strip()]
    for a in amplitudes:
        if a <= 0 or a > MAX_AMPLITUDE:
            parser.error(f"amplitude {a} out of range (0, {MAX_AMPLITUDE}]")

    if not args.cli.exists():
        parser.error(f"{args.cli} not found -- build it first: cargo build --release")

    check_gui_not_running()

    print(f"Connect the AWG output to CH{args.channel} now (probe x1, DC coupling).")
    input("Press enter when ready...")

    result = calibrate_channel(
        args.cli, args.channel, scales, amplitudes, args.frequency,
        args.capture_chunk, args.trim, args.settle,
    )

    calibration = hc.load_calibration(args.out)
    calibration[str(args.channel)] = result
    hc.save_calibration(calibration, args.out)

    print(f"\nSaved calibration for CH{args.channel} to {args.out}:")
    print(f"  adc_center = {result['adc_center']:.2f}")
    for scale, entry in result["scales"].items():
        print(f"  {scale:6s}  volts_per_count={entry['volts_per_count']:.5f}  "
              f"counts_per_div={entry['counts_per_div']:.2f}")
    if result["counts_per_div_fit"]:
        print(f"  overall counts_per_div_fit = {result['counts_per_div_fit']:.2f}")


if __name__ == "__main__":
    main()

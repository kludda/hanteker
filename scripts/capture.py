#!/usr/bin/env python3
"""Set channel/scope config, capture one channel, and write a calibrated CSV.

Sets exactly the settings given below on the device via hanteker_cli, then
runs a single capture (-n 1, never more -- see CLAUDE.md on why multi-call
captures corrupt timing) and converts it straight to a time,voltage CSV
using hantek_utils.py. Everything else on the device (--probe, --coupling,
--enable, device mode, ...) is left exactly as it already is -- this script
only touches --scale/--offset (via `channel`) and --time-scale (via
`scope`).

Since there's no way to read the device's current settings back over USB
(see CLAUDE.md), you have to already know --channel/--scale/--offset/
--time-scale (e.g. by reading them off the physical screen) for the output
to be calibrated correctly.

--duration (seconds) picks --capture-chunk for you via --time-scale's
sample rate, capped to the confirmed-safe range (64-4096 samples, see
CLAUDE.md "Known single-call --capture-chunk sizes") -- pass
--capture-chunk directly instead if you need to go past that cap.

Output file: <YYYYMMDD-HHMMSS>_ch<channel>_<sample_rate_hz>Hz.csv
"""
import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

import hantek_utils as hu

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CLI = SCRIPT_DIR.parent / "target" / "release" / "hanteker_cli"
DEFAULT_CAPTURE_CHUNK = 4096  # known-safe single-call size, see CLAUDE.md
MIN_CAPTURE_CHUNK = 64  # device minimum, hanteker_lib panics below this
MAX_SAFE_CAPTURE_CHUNK = 4096  # highest CONFIRMED-safe size; larger has wedged the device, see CLAUDE.md


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


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--channel", type=int, required=True, choices=[1, 2])
    parser.add_argument("--scale", required=True, choices=sorted(hu.SCALE_VOLTS))
    parser.add_argument("--offset", type=float, default=0.0,
                         help="channel offset in volts (default: 0)")
    parser.add_argument("--time-scale", required=True, choices=sorted(hu.SECONDS_PER_DIV))
    parser.add_argument("--duration", type=float, default=None,
                         help="how long to capture for, in seconds -- computes "
                              "--capture-chunk from this and --time-scale "
                              "(mutually exclusive with --capture-chunk)")
    parser.add_argument("--capture-chunk", type=int, default=None,
                         help=f"samples to capture directly (default: {DEFAULT_CAPTURE_CHUNK} "
                              f"if neither this nor --duration is given)")
    parser.add_argument("--force", action="store_true",
                         help=f"bypass the {MAX_SAFE_CAPTURE_CHUNK}-sample safety cap on "
                              f"--duration. A single capture past this size has wedged the "
                              f"device before, needing a physical battery pull to recover "
                              f"-- see CLAUDE.md. Use deliberately.")
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI,
                         help=f"path to the hanteker_cli binary (default: {DEFAULT_CLI})")
    parser.add_argument("--out-dir", type=Path, default=Path("."),
                         help="directory to write the CSV into (default: current directory)")
    args = parser.parse_args()

    if args.duration is not None and args.capture_chunk is not None:
        parser.error("--duration and --capture-chunk are mutually exclusive")

    sample_rate = hu.sample_rate_for(args.time_scale)

    if args.duration is not None:
        capture_chunk = round(args.duration * sample_rate)
        if capture_chunk < MIN_CAPTURE_CHUNK:
            parser.error(
                f"--duration {args.duration}s at --time-scale {args.time_scale} "
                f"({sample_rate:,.0f} Sa/s) gives only {capture_chunk} samples, below "
                f"the device's {MIN_CAPTURE_CHUNK}-sample minimum. Increase --duration "
                f"or choose a slower --time-scale."
            )
        if capture_chunk > MAX_SAFE_CAPTURE_CHUNK and not args.force:
            max_duration = MAX_SAFE_CAPTURE_CHUNK / sample_rate
            parser.error(
                f"--duration {args.duration}s at --time-scale {args.time_scale} "
                f"({sample_rate:,.0f} Sa/s) would need a {capture_chunk}-sample capture, "
                f"above the {MAX_SAFE_CAPTURE_CHUNK}-sample confirmed-safe ceiling (larger "
                f"single captures have wedged the device before, see CLAUDE.md). Max safe "
                f"--duration at this --time-scale is ~{max_duration:.6f}s, or pick a coarser "
                f"--time-scale, or pass --force to bypass this cap."
            )
        elif capture_chunk > MAX_SAFE_CAPTURE_CHUNK:
            print(f"warning: --force set, requesting a {capture_chunk}-sample capture "
                  f"past the {MAX_SAFE_CAPTURE_CHUNK}-sample confirmed-safe ceiling", file=sys.stderr)
    elif args.capture_chunk is not None:
        capture_chunk = args.capture_chunk
    else:
        capture_chunk = DEFAULT_CAPTURE_CHUNK

    if not args.cli.exists():
        parser.error(f"{args.cli} not found -- build it first: cargo build --release")

    check_gui_not_running()

    run_cli(args.cli, "channel", "-c", str(args.channel), "--scale", args.scale,
             "--offset", str(args.offset))
    run_cli(args.cli, "scope", "--time-scale", args.time_scale)
    raw = run_cli(args.cli, "capture", "-c", str(args.channel), "-n", "1",
                   "--capture-chunk", str(capture_chunk))

    sample_interval = hu.sample_interval_for(args.time_scale)
    volts_per_count = hu.volts_per_count_for(args.scale)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{timestamp}_ch{args.channel}_{round(sample_rate)}Hz.csv"
    out_path = args.out_dir / filename

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_index", "time_s", "raw_value", "voltage"])
        for i, b in enumerate(raw):
            t = i * sample_interval
            v = hu.raw_to_voltage(b, volts_per_count, hu.CENTER_CODE, args.offset)
            writer.writerow([i, f"{t:.9e}", b, f"{v:.4f}"])

    print(f"wrote {out_path} ({len(raw)} samples, {len(raw) / sample_rate:.6f}s, "
          f"{sample_rate:,.1f} Sa/s, {volts_per_count:.5f} V/count, offset={args.offset}V)")


if __name__ == "__main__":
    main()

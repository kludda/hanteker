#!/usr/bin/env python3
"""Convert a raw hanteker_cli `capture` byte-stream into a CSV of sample_index,raw_value."""
import argparse
import csv
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="raw .bin capture file (or - for stdin)")
    parser.add_argument("output", help="output .csv file (or - for stdout)")
    args = parser.parse_args()

    data = sys.stdin.buffer.read() if args.input == "-" else open(args.input, "rb").read()
    out = sys.stdout if args.output == "-" else open(args.output, "w", newline="")

    writer = csv.writer(out)
    writer.writerow(["sample_index", "raw_value"])
    for i, b in enumerate(data):
        writer.writerow([i, b])

    if out is not sys.stdout:
        out.close()


if __name__ == "__main__":
    main()

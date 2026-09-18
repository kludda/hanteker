#!/usr/bin/env python3
"""FFT a raw hanteker_cli `capture` byte-stream and report the dominant frequency.

Pure-Python radix-2 FFT (no numpy dependency). The capture is zero-padded up
to the next power of two and a Hann window is applied to reduce spectral
leakage; the peak bin is then refined with quadratic (parabolic) interpolation
for sub-bin frequency resolution.

Sample rate is derived from --time-scale via the same verified formula used
by capture_to_csv.py: sample_rate = 100 / time_per_div_seconds (confirmed
exact against the device's own AWG across us1..us100). Pass --sample-rate
directly to override.
"""
import argparse
import cmath
import math
import sys

import hantek_utils as hu

SECONDS_PER_DIV = hu.SECONDS_PER_DIV


def fft(a):
    n = len(a)
    if n == 1:
        return a
    even = fft(a[0::2])
    odd = fft(a[1::2])
    result = [0] * n
    for k in range(n // 2):
        twiddle = cmath.exp(-2j * math.pi * k / n) * odd[k]
        result[k] = even[k] + twiddle
        result[k + n // 2] = even[k] - twiddle
    return result


def next_pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="raw .bin capture file (or - for stdin)")
    parser.add_argument("--time-scale", choices=sorted(SECONDS_PER_DIV),
                         help="derives --sample-rate via the verified formula")
    parser.add_argument("--sample-rate", type=float,
                         help="samples/sec; overrides --time-scale if both given")
    parser.add_argument("--top", type=int, default=5, help="print top N peaks")
    args = parser.parse_args()

    if args.sample_rate is not None:
        sample_rate = args.sample_rate
    elif args.time_scale is not None:
        sample_rate = 100.0 / SECONDS_PER_DIV[args.time_scale]
    else:
        parser.error("must pass either --time-scale or --sample-rate")

    data = sys.stdin.buffer.read() if args.input == "-" else open(args.input, "rb").read()
    samples = [float(b) for b in data]
    n = len(samples)
    mean = sum(samples) / n
    samples = [s - mean for s in samples]

    n_padded = next_pow2(n)
    windowed = [
        s * 0.5 * (1 - math.cos(2 * math.pi * i / (n - 1)))
        for i, s in enumerate(samples)
    ]
    windowed += [0.0] * (n_padded - n)

    spectrum = fft([complex(x, 0) for x in windowed])
    half = n_padded // 2
    mags = [abs(spectrum[k]) for k in range(half)]

    # skip DC and its immediate neighborhood
    skip = max(1, int(1 / (sample_rate / n_padded)))  # ignore < ~1Hz-ish region near DC, at least bin 1
    skip = 3
    candidates = sorted(range(skip, half - 1), key=lambda k: -mags[k])

    print(f"n_samples={n} n_padded={n_padded} sample_rate={sample_rate:,.1f} Sa/s "
          f"bin_width={sample_rate / n_padded:.3f} Hz")
    print(f"top {args.top} peaks:")
    seen_freqs = []
    for k in candidates:
        freq_bin = k * sample_rate / n_padded
        if any(abs(freq_bin - f) < (sample_rate / n_padded) * 5 for f in seen_freqs):
            continue
        seen_freqs.append(freq_bin)

        # parabolic interpolation around the peak for sub-bin accuracy
        y0, y1, y2 = mags[k - 1], mags[k], mags[k + 1]
        denom = (y0 - 2 * y1 + y2)
        delta = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
        refined_bin = k + delta
        refined_freq = refined_bin * sample_rate / n_padded

        print(f"  bin={k:6d}  freq={freq_bin:12.2f} Hz  refined={refined_freq:12.2f} Hz  "
              f"magnitude={mags[k]:.1f}")

        if len(seen_freqs) >= args.top:
            break


if __name__ == "__main__":
    main()

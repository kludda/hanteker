# hanteker — working notes for Claude

This is a fork of https://github.com/hkoosha/hanteker (CLI + lib for the Hantek
2D42/2D72 handheld oscilloscope/AWG/DMM combo device), updated to build against
`rusb` instead of the abandoned `libusb` crate. A sibling clone of
https://github.com/hkoosha/hanteker_gui lives at `../hanteker_gui` with the same
fix applied.

The device talks a reverse-engineered USB protocol with **no official
documentation** — everything about sample rates, calibration, and protocol
quirks below was derived empirically this session, on this specific unit. Trust
the verification methodology described here more than any single number if the
two ever conflict on a future device/firmware revision.

## Repo layout

- `/home/david/Documents/hanteker_cli/hanteker` — this repo (CLI + lib).
  Workspace members: `hanteker_lib` (protocol/device logic), `hanteker_cli`
  (the `hanteker_cli` binary). No `gui` feature target in this workspace's
  `Cargo.toml` — the GUI is a separate crate.
- `/home/david/Documents/hanteker_cli/hanteker_gui` — clone of `hanteker_gui`
  (druid-based GUI), patched to depend on the local fixed `hanteker_lib` and to
  use `rusb` directly too.
- `scripts/` (in this repo) — Python analysis tools, see below. No numpy/pip
  available in this environment; everything is pure-Python on purpose.

## Building

### hanteker_cli (this repo)

The upstream code used the `libusb` crate (FFI bindings to system libusb,
essentially unmaintained). Fixed by aliasing the crate name to `rusb` so
source code keeps saying `libusb::...`:

```toml
# hanteker_lib/Cargo.toml, hanteker_cli/Cargo.toml
libusb = { package = "rusb", version = "0.9" }
```

That alone doesn't compile — rusb's API differs from old libusb:

- `Device`/`DeviceHandle` dropped their lifetime parameter and became generic
  over `T: UsbContext` instead (`Device<'a>` → `Device<Context>`, same for
  `DeviceHandle`). Fixed in `hanteker_lib/src/device/usb.rs` (dropped the `'a`
  lifetime from `HantekUsbDevice`, uses concrete `Device<Context>` /
  `DeviceHandle<Context>`) and `hanteker_lib/src/models/hantek2d42.rs` (dropped
  `'a` from `Hantek2D42`).
- `Context::devices()` moved onto the `UsbContext` trait — needs
  `use libusb::UsbContext;` in scope.
- rusb's `Speed` enum is `#[non_exhaustive]` (extra variants like `SuperPlus`)
  — the match in `pretty_printed_device_info` needs a wildcard arm.

Build: `cargo build --release` from repo root. Binary at
`target/release/hanteker_cli`.

### hanteker_gui (sibling repo)

Same `libusb`→`rusb` alias needed in *its own* `Cargo.toml` too — it calls
`libusb::Context::new()` directly in `src/dev.rs`, independent of
`hanteker_lib`. Also point its `hanteker_lib` dependency at the local fixed
path instead of the stale crates.io `0.4.0` release:

```toml
# hanteker_gui/Cargo.toml
libusb = { package = "rusb", version = "0.9" }
# hanteker_lib = { version = "0.4.0", features = ["gui"] }
hanteker_lib = { path = "../hanteker/hanteker_lib", version = "0.4.0", features = ["gui"] }
```

No source changes needed in hanteker_gui itself once Cargo.toml is fixed.

System deps for the druid/GTK backend (not installed by default):
`sudo apt install -y libgtk-3-dev libglib2.0-dev libcairo2-dev libpango1.0-dev libgdk-pixbuf2.0-dev`

Build: `cargo build --release` from `hanteker_gui/`. Binary at
`hanteker_gui/target/release/hanteker_gui`. First build pulls druid from git
(pinned rev) and takes a few minutes.

## USB permissions

The device (vid `0483`, pid `2d42`) enumerates as root-only by default. Fix
with a udev rule (needs the user to run `sudo` interactively — I can't supply
a password):

```
# /etc/udev/rules.d/99-hantek.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="2d42", MODE="0666", GROUP="plugdev"
```

Install with `sudo cp ... && sudo udevadm control --reload-rules && sudo udevadm trigger`,
then replug the device.

## CLI basics

```
hanteker_cli [OPTIONS] <SUBCOMMAND>
  --timeout <ms>   USB timeout (default 1000)
  -v / -s          verbose / silent logging

SUBCOMMANDS:
  print                                          device info (manufacturer/product/speed)
  device -m <scope|awg|dmm> [--start|--stop]     switch device function/display mode
  channel -c <1|2> [--enable|--disable] [--coupling ac|dc|gnd] [--scale ...] [--probe x1|x10|x100|x1000] [--offset V] [--enable-bandwidth-limit|--disable-...]
  scope [--time-scale ...] [--trigger-*] [--time-offset]
  awg [--type sin|square|ramp|trap|arb1..4] [--frequency Hz] [--amplitude V] [--offset V] [--duty-*] [--start|--stop]
  capture [-c 1|2] [-n num-captures] [--capture-chunk N] [-f]   → raw bytes to stdout
  shell -s <bash|zsh|fish|...>                    completion script
```

`--scale` values: `mv10 mv20 mv50 mv100 mv200 mv500 v1 v2 v5 v10`.
`--time-scale` values: `ns5..ns500, us1..us500, ms1..ms500, s1..s500` (1-2-5 sequence).

**Only one process can hold the USB device at a time** — `hanteker_cli` and
`hanteker_gui` will fight over it (`error claiming any of usb interfaces` /
`error reading usb languages` if something else has it). Check with
`ps aux | grep hanteker_gui` before a CLI session; ask the user to close the
GUI if it's running.

**The GUI silently changes channel/scale/offset settings** when opened (it
applies its own last-used config on start). Always re-apply known settings via
CLI immediately before a precision capture — don't assume prior CLI settings
persisted if the GUI ran in between.

### Recommended setup sequence before capturing

```
hanteker_cli device -m scope --start
hanteker_cli channel -c 1 --enable --scale v1 --coupling dc --probe x1 --offset 0
hanteker_cli scope --time-scale us10
```

Only touch `awg ...` if the user actually wants the signal source changed —
otherwise leave it alone (it holds its config independently of `device -m`).

### Device can wedge

A single `capture` request for too many samples in one call (tested:
40960 in one `-n 1 --capture-chunk 40960` call) locked up the device's USB
control interface — even `print` failed afterward
(`error reading usb languages`), though it stayed visible in `lsusb`. Recovery
required **pulling the batteries** (full power cycle), which also resets
*all* device settings (mode, channel config, timebase, AWG) — everything
must be reapplied after that. Stay conservative with `--capture-chunk` on a
single call (see limits below) to avoid this.

## Capture semantics — READ BEFORE TRUSTING TIMING/FREQUENCY DATA

`capture -c <ch> -n <N> --capture-chunk <M>` calls the underlying
`hantek.capture(channel, M)` **N separate times** and concatenates the raw
bytes. Each call is an **independent trigger** — there is no guaranteed phase
or timing continuity between separate calls. Using `-n > 1` for anything
where timing matters introduces large, real errors (empirically: an 8.7%
frequency error from stitching 40× 1000-sample chunks together and treating
it as one continuous signal).

**Rule: for anything frequency/timing-sensitive, always use `-n 1` with a
single large `--capture-chunk`, never `-n > 1`.**

Even a *single* `capture()` call isn't perfectly continuous at the protocol
level: internally it re-issues the same `SCOPE_START_RECV` write command
before every ≤64-byte USB sub-read (see `capture()` in
`hanteker_lib/src/models/hantek2d42.rs`). In practice this
occasionally (~44% of captures in one small test batch) produces a single
spurious/corrupted zero-crossing inside an otherwise-clean capture — visible
as one implausibly-short period sandwiched between two normal ones, or one
badly-off period late in the capture. **Sanity-check period-to-period
consistency before trusting a zero-crossing-based measurement**; the FFT
method is more robust to this (one bad glitch reads as a small peak, buried
in the noise floor) and should be preferred when the raw crossings look
inconsistent.

### Known single-call `--capture-chunk` sizes

- 1000 (default), 1024, 1536, 2048, 3072, 4096: all confirmed working single
  calls (post power-cycle) with the current firmware.
- 40960 in one call: **wedged the device** (see above). The real ceiling is
  somewhere between 4096 and 40960 and was not characterized further — if a
  larger single capture is needed, step up cautiously in a few-thousand-sample
  increments and verify `print` still works after each attempt, rather than
  jumping straight to a big number.
- If more total samples are needed than a safe single call provides, prefer
  accepting the coarser frequency resolution of a smaller single capture over
  using `-n > 1` to get more samples — the timing corruption from multi-call
  stitching is worse than the resolution loss.

## Interpreting captured bytes

`capture` writes **raw unsigned 8-bit ADC counts** (0-255) to stdout — no
header, no timestamps, no units. Nothing else is encoded in the stream.

### Sample rate — VERIFIED formula

```
sample_rate (Sa/s) = 100 / time_per_div_seconds
```

i.e. the device always samples such that exactly 1000 samples would span
10 divisions — a fixed 100-samples/div design — **independent of the
`--capture-chunk`/`-n` size actually requested**. This was verified two
independent ways:

1. Against the device's own AWG at exact known frequencies (2 kHz, 20 kHz,
   50 kHz, 100 kHz) across a 100× range of `--time-scale` (us100 down to
   us1) — matched the formula exactly every time, via period-counts reported
   by the user off the physical display.
2. Independently re-verified via a clean **single-call, `-n 1`** capture at
   `us10` against a known 27,610 Hz reference (confirmed both by the AWG's
   own frequency-setting readout *and* the scope's built-in hardware
   frequency counter — agreeing on 27,610 Hz): measured sample rate came out
   to ≈9,969,374 Sa/s vs. the formula's predicted 10,000,000 Sa/s, a 0.31%
   discrepancy consistent with normal measurement noise from a couple of
   periods.

A `102.4/time_per_div` variant (guessing the internal buffer is a
power-of-two 1024 rather than 1000) was explicitly tested and **does not
fit** (−2.6% vs. the clean data, worse than plain 100). Don't reintroduce
that hypothesis without new evidence.

An **intermediate, now-superseded** finding said sample rate had to be
measured per-timebase with no formula, based on inconsistent captures — that
inconsistency was actually caused by the `-n > 1` chunking artifact above,
not a real property of the device. Trust the formula.

`SECONDS_PER_DIV` lookup table for every `--time-scale` value is in
`scripts/capture_to_csv.py` and `scripts/fft_freq.py` — use
`sample_rate = 100 / SECONDS_PER_DIV[time_scale]`.

### Voltage calibration — settled via a physical measurement, not curve-fitting

```
voltage = (raw_byte - 128) * volts_per_count
volts_per_count = selected_scale_in_volts_per_div / 25
```

**This is the adopted formula** (implemented as `COUNTS_PER_DIV = 25`,
`CENTER_CODE = 128` in `scripts/hantek_utils.py`), derived from a
direct physical measurement of the device rather than any capture-based
curve fit:

- The display shows ±4 divisions vertically.
- The offset control moves the trace by a fixed **25 button-presses per
  division**.
- A known 2V signal at `0.5V/div` (i.e. sitting 4 divisions from center)
  starts clipping at **~28 button-presses** of added offset in one
  direction — 28/25 ≈ 1.12 extra divisions, so the ADC's half-range is
  4 + 1.12 ≈ 5.12 divisions, full range ≈ 10.24 divisions.
- `256 counts / 10.24 divisions = 25.0 counts/div` *exactly* — matching the
  button-press step size, which strongly suggests each button press moves
  the offset by exactly 1 raw ADC count (25 presses = 1 division = 25
  counts), a clean, plausible firmware design rather than a coincidence.

This method has essentially no dependence on cable/connection noise,
capture-buffer artifacts, or AWG amplitude accuracy — it only requires
reading the on-screen division count and the button presses to clip,
things the device shows/does directly. **Trust this over the AWG-based
fit below.**

Only verified at `--probe x1`; other probe attenuations untested.

<details>
<summary>Superseded: AWG-based curve fit (kept for reference, more noise-prone)</summary>

An earlier session fed CH1 from the device's own AWG (`awg --type square
--frequency 1000 --offset 0`) and swept amplitude/scale, fitting
`volts_per_count ≈ scale/24` (vs. the `/25` physical answer above — within
~4%). That approach turned out to be quite fragile in practice: a later
session hit escalating "stuck" readings scale-to-scale (frozen,
amplitude-independent plateaus, non-standard ADC centers ~107-119) that
were eventually traced to an intermittent physical connection issue on the
AWG→channel cable, not a real property of the device — some of the
"clean-looking" curve-fit data from the first session may have been
affected by milder versions of the same issue without being caught. The
button-press method above sidesteps all of this since it doesn't depend on
a second signal path (AWG → cable → channel) being clean at all.

The AWG-based calibration script and its per-channel calibration.json
output were removed (see git history if the approach is ever worth
revisiting) -- `scripts/hantek_utils.py` now just hardcodes the /25
physical formula.

</details>

#### Capture buffer contamination at head/tail — READ BEFORE MEASURING PP/MIN/MAX

A single `capture --capture-chunk 4096` call is **not uniformly valid data**:
the first ~400-470 samples and the last ~460-510 samples of every capture
this session were a near-ADC-midpoint filler value (bouncing in the
123-134 range, unaffected by `--scale`, i.e. clearly not real amplified
CH1 signal) — roughly the first/last ~11% of the buffer in each case, with
the boundary position varying capture-to-capture (seen from as early as
sample ~417 to as late as ~467 at the head, symmetric behavior at the
tail). Only the middle ~70-75% of any single capture is trustworthy.

This is presumably a bigger-scale manifestation of the same chunked
re-triggering behavior already documented above (`capture()` re-issuing
`SCOPE_START_RECV` before every ≤64-byte USB sub-read) — it may explain
some of the previously-reported "spurious zero-crossing" glitches too.
**When computing peak-to-peak/min/max/any amplitude statistic from a raw
capture, trim a safe margin (this session used 600 samples) off both ends
first**, or use a robust statistic (mode of values above/below the
midpoint) that isn't dominated by two contiguous contaminated runs.

A later capture (mv500 scale, large-swing square wave, where the two real
signal levels were far enough apart to make the artifact obvious) showed
the actual *mechanism* more clearly than the original near-center-blob
description above: the head/tail regions aren't a fixed filler value, they
show a **period-2 alternation** — every other sample jumping between two
distinct levels (looked like an interleaved/misaligned readback, e.g.
CH1/CH2 or two internal registers), completely different from the real
~100-sample-period square wave in the middle of the buffer. The good,
trustworthy region was still ~85% of the buffer in the middle either way.

Trigger level (`scope --trigger-level`) is a separate device setting (where
the trigger fires) — unrelated to this voltage calibration, don't conflate
the two.

## Analysis scripts (`scripts/`, pure Python, no numpy/pip needed)

- `raw_to_csv.py <in.bin> <out.csv>` — dumps `sample_index,raw_value`, zero
  assumptions, always correct.
- `capture_to_csv.py --time-scale <X> --scale <Y> <in.bin> <out.csv>` —
  calibrated `sample_index,time_s,raw_value,voltage` using the formulas
  above (`--scale` picks the right volts/count for that vertical range,
  defaults to `v1`). Override `--sample-interval`, `--volts-per-count`,
  `--center-code` directly if needed.
- `fft_freq.py --time-scale <X> <in.bin> [--top N]` — pure-Python radix-2 FFT
  (zero-padded to next power of 2, Hann-windowed, parabolic peak
  interpolation for sub-bin accuracy). Validated against a synthetic
  known-frequency sine (recovered 12345.6789 Hz to within 0.02%, with a
  correctly-small ~85×-weaker leakage sidelobe) — trust the FFT math itself.
  Prints top N peaks by magnitude with both raw-bin and interpolated
  frequency. A real single-tone signal shows one dominant peak ≥40-80× its
  next-largest neighbor; anything with a strong peak family at even multiples
  (comb-like) usually means either genuine harmonic distortion/intermod in
  the signal, or a capture-artifact (check whether `-n > 1` was used).

## Doing a capture-and-FFT task end to end

When asked something like *"capture from the scope so we can FFT in the
~50 kHz range at ~5 V amplitude"*:

1. `ps aux | grep hanteker_gui` — make sure nothing else holds the USB
   device; ask the user to close the GUI if it's running.
2. `hanteker_cli print` — confirm the device answers at all before doing
   anything else.
3. Pick `--time-scale`: need `sample_rate = 100/time_per_div` comfortably
   above the signal frequency (aim for high oversampling, we've used
   100-300×+ margin successfully) **and** enough total samples at that rate
   for decent FFT bin resolution given the single-call size ceiling
   (~4096 samples known-safe). E.g. for ~50 kHz: `us10` gives 10 MSa/s
   (200× oversampling) — with 4096 samples that's a ~2.4 kHz bin width,
   usable but coarse; `us50` gives 2 MSa/s (40× oversampling) with the same
   4096 samples for a ~488 Hz bin width — better resolution, still huge
   headroom over Nyquist. Prefer the slower timebase that still keeps
   sample_rate ≳ 10-20× the target frequency, to get better resolution out
   of the same sample-count ceiling.
4. Pick `--scale`: need enough vertical range that the expected amplitude
   won't clip (raw byte hitting 0 or 255). For a stated ~5 V amplitude,
   start with `--scale v10` (10 V/div, generous headroom) rather than
   guessing tightly — the voltage calibration extrapolation above is not
   trustworthy enough to cut it close. Adjust the scale up/down after
   checking the first capture's min/max.
5. Apply settings: `device -m scope --start`, `channel -c <ch> --enable
   --scale <X> --coupling dc --probe x1 --offset 0`, `scope --time-scale
   <X>`. Do **not** touch `awg ...` unless the user asked for the source
   signal itself to change.
6. Capture: `capture -c <ch> -n 1 --capture-chunk <safe size, ≤4096 unless
   tested higher>` to a file. **Never `-n > 1`** for this kind of task.
7. Check for clipping: read the raw bytes, confirm `min > 0` and `max < 255`
   with real headroom. If clipped, back off `--scale` (bigger V/div) and
   recapture. If the swing is tiny, tighten `--scale` (smaller V/div) and
   recapture — don't analyze a clipped or barely-visible capture.
8. Run `scripts/fft_freq.py --time-scale <X> <file>`, report the dominant
   peak's interpolated frequency, and flag if the spectrum looks like a
   single clean tone vs. has a suspicious harmonic/comb pattern (which may
   mean recapturing, or may be a real property of the signal — say which).
9. If the user wants a voltage/time CSV too, run `capture_to_csv.py`, but
   caveat the voltage numbers per the calibration section above unless it's
   been freshly recalibrated at that exact `--scale`.

## Open items for a future session

- Voltage calibration is now settled by a physical measurement
  (`volts_per_count = scale/25`, center=128 — see above) rather than the
  earlier noisy AWG curve fit. Only remaining gap: verified at `--probe x1`
  only. Worth repeating the button-press clipping check at x10/x100/x1000
  if those probes end up in use, though there's no reason to expect the
  ADC-side constant (25 counts/div) to depend on probe attenuation at all.
- The capture head/tail contamination (new finding, see "Capture buffer
  contamination" above) needs characterization: is the contaminated region
  a fixed sample count, a fixed fraction, or time-based (e.g. tied to
  `--time-scale`)? Only tested at `--capture-chunk 4096`, `--time-scale
  ms1`, `-n 1`. Also worth checking whether it correlates with the ~44%
  single-call zero-crossing glitch rate noted below — same root cause?
- Exact single-call `--capture-chunk` ceiling between 4096 and 40960 not
  found. Worth bisecting carefully (with the user's attention, since a wedge
  needs a physical battery pull to fix) if larger single captures become
  necessary.
- The ~44% single-call glitch rate (spurious zero-crossing from the 64-byte
  sub-chunk re-triggering) was observed on a small sample (9 captures). Worth
  a larger-N characterization if it starts affecting results, and worth
  checking whether it correlates with anything (specific byte offsets, USB
  timing, etc.).
- This whole document reflects one specific physical unit/firmware. Re-verify
  the sample-rate formula on the user's next clone/device if it's a different
  unit.

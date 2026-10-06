# hanteker — working notes

Fork of https://github.com/hkoosha/hanteker (Rust CLI + lib for the Hantek
2D42/2D72 handheld oscilloscope/AWG/DMM), ported from the abandoned `libusb`
crate to `rusb`, plus Python scripts for capturing to calibrated CSV.

The USB protocol is reverse-engineered and undocumented. There is a seller
datasheet for the hardware (see "Datasheet"). Everything else here was
found by experiment on one physical unit. Each finding below says how it
was established; several early conclusions turned out to be wrong, so
treat anything marked "not reproduced" or "unverified" accordingly.

Status: the project is parked. See "Open items" for what was left.

## Repo layout

- `hanteker_lib/` — protocol and device logic (workspace member).
- `hanteker_cli/` — the `hanteker_cli` binary (workspace member).
- `hanteker_gui/` — copy of https://github.com/hkoosha/hanteker_gui
  (druid GUI) with the same `rusb` fix. Tracked in this repo but **not** a
  workspace member. Its `Cargo.toml` depends on
  `../hanteker/hanteker_lib`, a path written for a sibling-directory
  layout that does not exist here; it would need `../hanteker_lib` to build
  from where it sits. Building it from this location was not tried.
- `scripts/` — Python tools, standard library only (no numpy).
- `99-hantek.rules` — udev rule, see "USB access".

## Building

`cargo build --release` (or `make build`) from the repo root. Binary:
`target/release/hanteker_cli`. Needs `libusb-1.0-0-dev` and `pkg-config`
on Linux.

What the `rusb` port changed, in case it needs redoing against a newer
upstream:

- Both crates alias the dependency so source still says `libusb::`:
  `libusb = { package = "rusb", version = "0.9" }`.
- `Device`/`DeviceHandle` lost their lifetime parameter and are generic
  over `UsbContext`; `HantekUsbDevice` (`hanteker_lib/src/device/usb.rs`)
  and `Hantek2D42` (`hanteker_lib/src/models/hantek2d42.rs`) dropped `'a`
  and use `Device<Context>` / `DeviceHandle<Context>`.
- `Context::devices()` moved to the `UsbContext` trait (`use
  libusb::UsbContext;`).
- `rusb::Speed` is `#[non_exhaustive]`; the match in
  `pretty_printed_device_info` needs a wildcard arm.

The GUI additionally needs the GTK dev packages:
`libgtk-3-dev libglib2.0-dev libcairo2-dev libpango1.0-dev libgdk-pixbuf2.0-dev`.

## USB access

The device (vid `0483`, pid `2d42`) is root-only by default. Install
`99-hantek.rules` into `/etc/udev/rules.d/`, reload udev, replug. This
needs `sudo`, which an agent cannot supply.

Only one process can hold the device. If the GUI is running, CLI calls fail
with `error claiming any of usb interfaces` or `error reading usb
languages`. The GUI also applies its own channel/scale/offset settings to
the device when it opens.

## Device behaviour over USB

All of these were observed directly.

- **Settings are write-only.** There is no command to read scale, offset,
  coupling, probe, timebase or channel-enable back. `get_config()` in the
  lib is its own in-memory record, empty at the start of every CLI call.
  To convert a capture you must already know the settings: set them
  yourself, or have the user read them off the screen.
- **Device settings persist between CLI calls**, so `capture` works on its
  own and digitises with whatever is currently set.
- **`channel --offset` needs `--scale` in the same call.** The lib derives
  the offset range from the scale and has no memory across calls; without
  it the call fails with `missing or bad channel adjustment`.
- **`capture` fails with `failed to read from usb` on a freshly started
  scope until `scope --time-scale` has been set once.**
- **Transient `failed to read from usb`** errors also occur occasionally
  right after changing scale. The device stays healthy (`print` works);
  retrying after a second or so succeeds.
- **The AWG sometimes does not start.** `awg ... --start` returns success
  but no signal appears. Stopping and starting it on the device fixed it.
  After starting the AWG, check a capture for the expected swing before
  trusting anything measured from it.
- **The CLI warns that offset and running status "will not be updated
  properly in the UI"** on some commands. The settings do take effect; only
  the device's on-screen indication lags.
- **`pgrep -f hanteker_gui` from a shell matches its own command line.**
  Use `pgrep -x hanteker_gui` or check from a subprocess call without a
  shell, as `capture.py` does.

### Capture size — keep it at or below 3000 samples

`capture -c <ch> -n 1 --capture-chunk <N>`:

| N | Result |
| --- | --- |
| 3000 | Clean. Verified with a 1 kHz square wave at `ms1`: 50-sample plateaus from first sample to last in two captures; a third was checked only for junk and had none. |
| 4096 | Samples 0–3583 clean; the last 512 are junk. Two captures. |
| 6000 | About 1022 junk samples at ~4536–5559; the square wave resumes after them at a different phase, and one capture also had a phase jump at sample 3107. Two captures. |
| 40960 | USB control interface locked up (`print` failed, device still in `lsusb`). Needed the batteries pulled. |
| 2,000,000 | Device dropped off the USB bus and powered itself off. |

The junk is byte-for-byte the same in every capture
(`123, 125, 124, 125, 123, 125, ...`, range 122–127) and also appears with
no input signal, so it is buffer content, not signal. The 4096 and 6000
tests were run with CH2 disabled, as was the third 3000-sample capture.
CH2's state during the first two 3000-sample captures is not known.

`scripts/capture.py` caps at 3000 for this reason. A power cycle resets all
device settings.

Smaller sizes used without problems: 1000, 1024, 1536, 2048.

### `-n` greater than 1 breaks timing

`capture -n N` makes N separate acquisitions and concatenates them. There
is no phase continuity between them; treating 40 × 1000 samples as one
signal gave an 8.7% frequency error. Always use `-n 1`. Note the CLI's
default for `-n` is unlimited.

### Earlier observations that were not reproduced

Recorded because they were seen, but do not rely on them:

- **Junk at the head and tail of 4096-sample captures** (roughly the first
  400–470 and last 460–510 samples, alternating between two levels on every
  other sample). Seen repeatedly in early sessions. In the later tests with
  CH2 disabled there was no junk at the head of any capture. A plausible
  explanation is that CH2 was enabled earlier and 4096 exceeded the shared
  record length, but this was not tested.
- **A spurious zero-crossing in about 4 of 9 single captures**, attributed
  to `capture()` re-sending `SCOPE_START_RECV` before each 64-byte USB
  read. Not seen in the later 3000-sample square-wave captures (all runs
  were 50 ± 2 samples).
- **A settle time of 1–3 s after changing scale.** The data behind this was
  later explained by the head junk above.

## Converting captured bytes

`capture` writes raw unsigned 8-bit ADC codes, nothing else.

```
sample_rate = 100 / seconds_per_div           (Sa/s)
voltage     = (raw - 128) * (volts_per_div / 25) - channel_offset_volts
```

Implemented in `scripts/hantek_utils.py`.

### Sample rate

100 samples per division, independent of capture size.

- Verified at `us1`..`us100` against the device's AWG at 2, 20, 50 and
  100 kHz, by counting periods.
- Verified at `us10` with one clean capture against a 27,610 Hz reference
  (AWG setting and the scope's own frequency counter agreed): 0.31% off.
- Consistent at `ms1` with a 1 kHz square wave (50-sample plateaus).
- A `102.4 / seconds_per_div` variant was tested and fits worse (−2.6%).
- **Unverified at `ns5`..`ns500`.** The formula gives 200 MSa/s to
  20 GSa/s there, above the datasheet's ADC rate (250 MSa/s one channel,
  125 MSa/s two). The datasheet lists `(sin x)/x` interpolation, so the
  device most likely interpolates. One attempt to detect this by comparing
  noise at `us1` and `ns5` was inconclusive, and the AWG (25 MHz max)
  cannot produce a signal fast enough to settle it. `hantek_utils` prints a
  warning above 125 MSa/s.

### Voltage scale: 25 codes per division, centre 128

- The lib maps `--offset` linearly onto a 0–200 byte across ±4 divisions:
  25 steps per division (`set_channel_offset_with_auto_adjustment`).
- On the device, the offset buttons move the trace 25 presses per division
  (user observation).
- Setting `--offset 1.0` at `v1` moved the measured centre by 25.1 codes.
  So one offset step is one ADC code, and a division is 25 codes.
- A 2 V signal at 0.5 V/div started clipping after about 28 more presses
  (user observation): 4 × 25 + 28 = 128, half the 8-bit range.

Cross-check against the AWG: a ±1.0 V square wave at `v1` reads codes
103/151 (48 codes peak-to-peak, expected 50), and ±2.0 V at `v1` and
`mv500` read 98 and 196 (expected 100 and 200). So readings come out 2–4%
below the AWG setting. The AWG's own accuracy is unknown and the datasheet
gives ±3% DC gain accuracy, so this was left alone.

Only checked with probe x1. The probe setting was never tested; the user's
understanding is that the device handles it.

### Channel offset

The offset shifts the ADC codes, not just the picture (the +25.1 code test
above), hence the `- channel_offset_volts` term. The device rounds the
offset to one code, so a requested offset that is not a multiple of
`volts_per_div / 25` leaves an error of up to one code. Offsets beyond
±4 divisions are not range-checked by the scripts.

### AWG amplitude

`awg --amplitude` is a peak value: the output swings ±amplitude into a
high-impedance input (2.5 max, matching the datasheet's 5 Vpp into high-Z).

## Scripts

- `capture.py --channel N --scale S --time-scale T [--offset V]
  [--duration SEC | --capture-chunk N]` — sets scale, offset and timebase,
  takes one capture, writes
  `<YYYYMMDD-HHMMSS>_ch<N>_<sample_rate>Hz.csv` with columns
  `sample_index,time_s,raw_value,voltage`. Leaves probe, coupling, channel
  enable and device mode as they are. Size limited to 64–3000 samples;
  `--force` bypasses the upper limit and then also disables the other
  channel.
- `capture_to_csv.py` — the same conversion for an already-saved raw file.
- `raw_to_csv.py` — raw codes to CSV, no conversion.
- `fft_freq.py` — radix-2 FFT with Hann window and parabolic peak
  interpolation; prints the strongest peaks. Checked against a synthetic
  sine (within 0.02%) and a captured 1 kHz square wave (1000.2 Hz plus odd
  harmonics).
- `hantek_utils.py` — the lookup tables and formulas above.

## Capturing a signal on request

1. Check nothing else holds the device, then `hanteker_cli print`.
2. Get channel, scale, offset and timebase from the user (read off the
   screen), or choose them: timebase so the sample rate is 10–20× the
   signal frequency or more, scale so the signal will not clip.
3. If the device was just powered on: `device -m scope --start` and
   `channel -c N --enable --coupling dc --probe x1`.
4. `python3 scripts/capture.py --channel N --scale S --offset V --time-scale T`.
5. Check the CSV's `raw_value` column stays away from 0 and 255. If it
   clips, use a larger scale and recapture.
6. For frequency, capture raw bytes with `hanteker_cli capture -c N -n 1
   --capture-chunk 3000 > file.bin` and run `fft_freq.py --time-scale T
   file.bin`. With 3000 samples the bin width is about `sample_rate / 4096`.
7. Do not touch the AWG unless asked.

## Datasheet

From the seller's spec sheet; not checked against this unit except where
noted above.

- 2 channels, 70 MHz bandwidth, 8-bit ADC, rise time ≤ 5 ns.
- Sampling rate 250 MSa/s one channel, 125 MSa/s two channels.
- Record length 6000 samples one channel, 3000 two channels (but see
  "Capture size").
- 5 ns/div – 500 s/div; 10 mV/div – 10 V/div; measurement range ±5 div;
  `(sin x)/x` waveform interpolation; DC gain accuracy ±3%.
- Trigger: edge; auto/normal/single; level ±4 div; CH1 or CH2.
- Input: DC/AC/GND; 1 MΩ, 25 pF; probe factors 1×/10×/100×/1000×;
  150 Vrms protection.
- AWG: sine to 25 MHz, square to 10 MHz, ramp to 1 MHz; 250 MSa/s; 2.5 Vpp
  into 50 Ω, 5 Vpp into high impedance; 50 Ω output.
- DMM: 4000 counts; 600 V, 10 A max.
- Display 320×240; 2 × 2600 mAh batteries.

## Open items

- Sample-rate formula at `ns5`..`ns500` is unverified; needs a reference
  signal well above 25 MHz.
- Whether the 3000-sample limit depends on CH2 being enabled, and why
  captures above ~3584 samples contain junk, was not investigated.
- The head/tail junk and spurious zero-crossing seen in early sessions were
  never explained.
- Voltage scale checked at probe x1 only.
- `hanteker_gui` does not build from its location in this repo without
  fixing its `hanteker_lib` path.
- From the code review, not done: the scripts have no tests; USB failures
  in `capture.py` surface as Python tracebacks with no retry; the output
  filename has one-second resolution.

### Hanteker
Hantek 2D42 (and possibly 2D72) handheld oscilloscope tool for Linux, Mac and Windows.

This is a fork of https://github.com/hkoosha/hanteker, updated to build against
`rusb` instead of the abandoned `libusb` crate. GUI: https://github.com/hkoosha/hanteker_gui

### Requirements

- Rust toolchain (`cargo`, stable) — https://rustup.rs
- `libusb-1.0` development headers + `pkg-config` (Linux), needed by the
  `rusb` crate:
  ```
  sudo apt install -y libusb-1.0-0-dev pkg-config
  ```

### Clone

```
git clone git@github.com:kludda/hanteker.git
cd hanteker
```

### Build

Builds the whole workspace (`hanteker_lib` + `hanteker_cli`):

```
cargo build --release
```

The `hanteker_cli` binary is written to `target/release/hanteker_cli`.

### USB permissions (Linux)

The device (vid `0483`, pid `2d42`) enumerates as root-only by default.
Install the provided udev rule so it's accessible without `sudo`:

```
sudo cp 99-hantek.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and replug the device.

### Run

```
target/release/hanteker_cli print
```

Or install it onto your `PATH`:

```
cargo install --path hanteker_cli
hanteker_cli print
```

Only one process can hold the device at a time — close the GUI before
running CLI commands, and vice versa.

### CLI commands

Global options (apply to every subcommand): `--timeout <ms>` (default 1000),
`-v`/`--verbose` (raise log level), `-s`/`--silent` (lower log level, wins
over `-v`), `--no-quirks` (suppress UI-quirk warnings).

| Command | Description | Key options |
| --- | --- | --- |
| `print` | Print device info (manufacturer, product, USB speed) | — |
| `device` | Switch device function / start or stop the display | `-m, --mode <scope\|awg\|dmm>` · `--start` · `--stop` |
| `channel` | Configure a scope channel | `-c, --channel <1\|2>` · `--enable` / `--disable` · `--coupling <ac\|dc\|gnd>` · `--probe <x1\|x10\|x100\|x1000>` · `--scale <mv10\|mv20\|mv50\|mv100\|mv200\|mv500\|v1\|v2\|v5\|v10>` · `--offset <V>` · `--enable-bandwidth-limit` / `--disable-bandwidth-limit` · `-f, --force-mode` |
| `scope` | Configure scope timebase and trigger | `--time-scale <ns5..s500>` · `--time-offset <s>` · `--trigger-source <channel>` · `--trigger-slope <rising\|falling\|both>` · `--trigger-mode <auto\|normal\|single>` · `--trigger-level <V>` · `-f, --force-mode` |
| `awg` | Configure the arbitrary waveform generator | `-t, --type <square\|ramp\|sin\|trap\|arb1..arb4>` · `--frequency <Hz>` · `-a, --amplitude <V>` · `-o, --offset <V>` · `--duty-square <%>` · `--duty-ramp <%>` · `--duty-trap-rise/-high/-low <%>` · `--start` · `--stop` · `-f, --force-mode` |
| `capture` | Capture raw ADC samples from one or more channels to stdout | `-c, --channel <1\|2>` (repeatable) · `--capture-chunk <N>` (default 1000) · `-n, --num-captures <N>` (default infinite) · `-f, --force-mode` |
| `shell` | Generate a shell completion script | `-s, --shell <bash\|zsh\|fish\|...>` · `-n, --name-override <name>` |

`--time-scale` accepts the 1-2-5 sequence at every decade:
`ns5, ns10, ns20, ns50, ns100, ns200, ns500, us1, us2, us5, us10, us20, us50,
us100, us200, us500, ms1, ms2, ms5, ms10, ms20, ms50, ms100, ms200, ms500,
s1, s2, s5, s10, s20, s50, s100, s200, s500`.

Run `hanteker_cli <command> --help` for the full, authoritative list of
flags for any command.

### Channel zero-level (vertical offset)

The zero-level you can drag/move on the physical display (or step with the
offset buttons) is fully controllable over USB via
`channel -c <1|2> --offset <V>` — same underlying command the buttons send.

On the wire it's a single raw byte in the range 0-200, sent with command
`SCOPE_OFFSET_CH1`/`SCOPE_OFFSET_CH2` (`hanteker_lib/src/models/hantek2d42_codes.rs`).
`hanteker_cli` converts your `--offset` value (volts) into that raw byte for
you, linearly across a ±4-division window around whatever `--scale` is
currently set (`hanteker_lib/src/models/hantek2d42.rs`,
`set_channel_offset_with_auto_adjustment`) — i.e. `--offset` is clamped to
roughly `±4 × scale` volts before it clips off-screen.

**`--scale` must be given together with `--offset` in the same `channel`
invocation.** Every `hanteker_cli` call is a fresh process with no memory of
earlier ones, and the offset conversion needs to know the current scale (to
compute that ±4-division window) — passing `--offset` alone, without
`--scale` in that same call, fails with "missing or bad channel adjustment".
E.g.:

```
hanteker_cli channel -c 1 --scale v1 --offset 0.25
```

### Disclaimer
I take no responsibility if this app breaks your oscilloscope! use at your own risk.

### Original Work
This is port of the C application to Rust, available at: https://github.com/lucaoli/Hantek.

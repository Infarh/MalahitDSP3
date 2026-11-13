---
name: malahit-dsp3-control
description: Control a Malahit DSP3 SDR receiver over its USB CAT serial port - tune frequency, set demodulation mode, read S-meter, identify the port. Use when asked to tune, scan, query or automate a Malahit DSP, Malachite, or Malahit-DSP2/DSP3/DSP4 receiver, or when a Kenwood TS-480 style CAT port answers ID021.
---

# Malahit DSP3 CAT control

## Discovery

The CAT port is the `MI_00` interface of USB `VID_FFFF&PID_0737`. Do not match
on the COM number — it changes between replugs. Match on VID/PID:

```python
from serial.tools import list_ports
port = next((p.device for p in list_ports.comports()
             if p.vid == 0xFFFF and p.pid == 0x0737), None)
```

`p.hwid` looks like `USB VID:PID=FFFF:0737 SER=... LOCATION=1-3:x.0`; the
`vid`/`pid` attributes are the reliable fields.

Serial settings: **115200 8N1**, no flow control. Open, wait ~300 ms, then
`reset_input_buffer()` — stale bytes break the first query.

## Command set

Kenwood TS-480 subset, `ID;` → `ID021;`. Only these 22 commands answer
(verified by brute-forcing all 676 two-letter combinations on firmware 2.62):

```
AG AI AN DA FA FB FR FT FV FW GC ID IF KS KY MD PA PS PT RA SH SL SM
```

Anything else returns `?;`.

| Query | Response | Meaning |
|---|---|---|
| `ID;` | `ID021;` | model / emulation id |
| `FA;` | `FA00010050000;` | VFO A frequency, 11-digit Hz |
| `MD;` | `MD4;` | mode: 1 LSB, 2 USB, 3 CW, 4 FM, 5 AM |
| `SM0;` | `SM00000;` | S-meter |
| `AG;` | `AG0100;` | AF gain |
| `RA;` | `RA0100;` | RF attenuator |
| `AN;` | `AN101;` | antenna input |
| `IF;` | `IF...;` | full status block |

Setters use the same prefix with a value before `;`:

```
FA00010050000;   tune to 100.500 MHz
MD2;             USB
```

## Traps

- **`SM` needs a parameter.** `SM0;` works; bare `SM;` returns `?;` on 2.62.
- **`FV;` is not the firmware version.** It returns the literal `FV1.00;` on
  every build — the string is hardcoded at offset `0x0E10AC` in the image,
  next to the other response formats (`ID%03d;`, `MD%1d;`, `FW%04d;`).
- **No CAT command reports the firmware version.** Read it from the RADIO
  menu on the device (bottom-right `FW: x.xx`).
- Frequencies are always 11 digits, zero padded.
- After a set command allow ~300-500 ms before reading back — tuning is applied
  asynchronously.

## Ready-made helper

[malahit.py](../../../malahit.py) implements this (`Cat` class; `info`, `get`,
`tune`, `scan` subcommands). Prefer it over re-writing serial code.

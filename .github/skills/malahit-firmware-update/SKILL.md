---
name: malahit-firmware-update
description: Update Malahit DSP1/DSP2/DSP3/DSP4 receiver firmware over USB DFU on Windows - enter DFU mode, install the WinUSB driver, flash with dfu-util, recover from a failed write. Use when asked to flash, update or reinstall firmware on a Malahit/Malachite receiver, or when dfu-util reports "Cannot open DFU device 0483:df11" or "Page at 0x08000000 is not writeable".
---

# Malahit firmware update over USB DFU

## Firmware sources

Official builds live at <https://malahiteam.com/dokumentacija/>. Match the file
to the model — never cross-flash:

| Model | Latest seen (Nov 2026) | File |
|---|---|---|
| DSP3 | 2.62 | `m3_2_62-1.zip` → `M3_FW2_62_101026.bin` (2 MiB) |
| DSP2 | 2.58 | `m2_2_58.zip` |
| DSP4 | 2.62 | `m4_2_62-1.zip` |

The site gates content behind a `beget` cookie; a plain `curl` returns an empty
page. Send `-H "Cookie: beget=begetok"`.

Firmware version is **not** readable over CAT or USB in normal mode — check the
RADIO menu on the device (`FW: x.xx`, bottom-right).

## Entering DFU (DSP2/DSP3/DSP4)

1. Power the receiver **off**.
2. Hold **both encoders** (VOL and ENC_FREQ).
3. Press and hold the **power** button.
4. Release both encoders.
5. Release power.
6. The side LED blinks **red/green**; the screen stays dark. Plug in USB.

Do steps 2-5 quickly — a slow sequence does not latch. The device then appears
as `MALAHIT RECEIVER DFU` / `0483:DF11`.

## Driver (Windows, one time)

A fresh DFU device shows **Code 28** (no driver) and `dfu-util` fails with
`LIBUSB_ERROR_NOT_SUPPORTED`. Windows has no inbox INF matching
`USB\Class_FE&SubClass_01`, so a WinUSB binding is required and it needs
administrator rights — the agent session usually does not have them.

Install [Zadig](https://zadig.akeo.ie/) (`zadig-2.9.exe`, signed by Akeo
Consulting) and launch it elevated:

```powershell
Start-Process -FilePath "$env:TEMP\zadig2.exe" -Verb RunAs -PassThru
```

In Zadig: **Options → List All Devices**, pick `MALAHIT RECEIVER DFU`,
target driver **WinUSB**, click **Replace Driver**. Do not touch the
`USB Serial Device` entry — that is the CAT port.

Verify:

```powershell
dfu-util.exe -l
# Found DFU: [0483:df11] ver=0200 ... "@Internal Flash /0x08000000/..."
```

## Flashing

dfu-util 0.11 win64 binaries come from
`https://dfu-util.sourceforge.net/releases/dfu-util-0.11-binaries.tar.xz`
(extract with the built-in `tar.exe`).

```powershell
dfu-util -d 0483:df11 -a 0 -s 0x08000000:force:leave -D M3_FW2_62_101026.bin
```

**`:force` is mandatory on Malahit.** The DfuSe descriptor marks the first
48 KiB as read-only:

```
Memory segment at 0x08000000   3 x 16384 = 49152 (r)     <- not writable
Memory segment at 0x0800c000   1 x 16384 = 16384 (rew)
...
```

Without `:force` dfu-util aborts with `Page at 0x08000000 is not writeable`.
The official WebUSB flasher does the same thing and documents it as
"matching dfu-util :force".

## Reading the result

```
Download done.
File downloaded successfully
Submitting leave request...
Error during download get_status     <- expected, device already left DFU
```

Exit code 74 with `Error during download get_status` **after**
`File downloaded successfully` is success: the device detached from the bus
while dfu-util was polling status. Confirm by re-enumeration — the normal
`VID_FFFF&PID_0737` composite device (COM port + 3 audio endpoints) should
reappear within a few seconds.

`Warning: Invalid DFU suffix signature` is harmless for a raw `.bin`.

## After flashing

- The receiver **stays off** and does not self-power-up.
- From firmware 2.50 onward power-on is a **~3 s hold** (or triple press when
  DIP switch 2 is ON), not a short press.
- DMR / D-STAR audio needs the AMBE codec: copy `mbe_arm_cm7.bin` from the
  firmware archive into a `Firmware` folder on the SD card.
- Settings may reset when jumping across major versions; record memory
  channels first.

## Recovery

An interrupted write does not brick the device — the STM32 **system**
bootloader is in ROM. Re-enter DFU with the button sequence and flash again.

---
name: malahit-iq-capture
description: Capture and process raw I/Q baseband from a Malahit DSP3 SDR receiver - record the 192 kHz stereo panorama to WAV, measure signal level, scan a band, demodulate FM. Use when asked for raw signal, I/Q, baseband, spectrum, waterfall, or audio capture from a Malahit/Malachite receiver, or when a sounddevice PortAudioError "Blocking API not supported yet" appears on a WDM-KS device.
---

# Malahit DSP3 raw I/Q capture

## Endpoints

The receiver exposes two independent audio inputs, both via **WDM-KS**:

| Device name | Channels | Rate | Content |
|---|---|---|---|
| `Malahit spectre (Malahit IQ)` | 2 | 192000 | raw panorama, **L = I, R = Q** |
| `Malahit RX` | 1 | 48000 | same signal already demodulated |

`Malahit Headphone` is the 48 kHz output. Device indices are not stable across
reboots — always resolve by name:

```python
import sounddevice as sd
iq = next(i for i, d in enumerate(sd.query_devices())
          if "malahit iq" in d["name"].lower() and d["max_input_channels"] == 2)
```

## The blocking-API trap

WDM-KS does not implement PortAudio's blocking read. This fails:

```python
sd.rec(..., device=iq)            # PortAudioError -9999
stream.read(1024)                 # PortAudioError -9999
```

`'Blocking API not supported yet' [Windows WDM-KS error -9999]`

Use a callback stream and collect from the callback thread:

```python
chunks = []
stream = sd.InputStream(device=iq, channels=2, samplerate=192000,
                        dtype="int16",
                        callback=lambda indata, *a: chunks.append(indata.copy()))
stream.start()
```

[malahit.py](../../../malahit.py) wraps this in `IqStream`, which also lets you
`flush()` between retunes so a scan does not mix samples from two frequencies.

## Sanity checks

- I and Q must be **uncorrelated**: `abs(corrcoef(I, Q)) < 0.05`. A high value
  means you opened the wrong device (e.g. a stereo audio stream, not I/Q).
- Level is reported in dBFS over the complex magnitude. Broadcast FM in a
  quiet band sits near `-35 dBFS`; dead spectrum is below `-55 dBFS`.
- A 1 s capture is 192000 frames = 768000 bytes as 16-bit stereo.

## WAV format

Write stereo 16-bit 192 kHz. HDSDR, SDR#, SDR++ and gqrx all open this
directly as an I/Q file. Do not interleave anything else, do not resample.

## Demodulation

FM discriminator on the complex stream, then decimate:

```python
z = I + 1j*Q
d = np.angle(z[1:] * np.conj(z[:-1]))     # instantaneous frequency
d = d[: len(d)//4*4].reshape(-1, 4).mean(axis=1)   # 192k -> 48k
```

Guard the reshape: a 1 s capture yields 191999 differences, which is not
divisible by 4 — trim with `len(d)//factor*factor` first.

A broadcast station tuned at centre shows a peak within a few tens of Hz of
0 Hz offset; demodulated programme material produces audio peaks in the
0.3-15 kHz range.

## Ready-made helper

[malahit.py](../../../malahit.py): `scan`, `record`, `demod` subcommands.

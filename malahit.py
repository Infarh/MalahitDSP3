#!/usr/bin/env python3
"""Control a Malahit DSP3 receiver and capture raw I/Q from it.

Two independent channels are used:

  * CAT  - USB serial port (Kenwood TS-480 command subset). Tuning, mode.
  * IQ   - "Malahit IQ" USB audio input, 192 kHz, stereo, left/right = I/Q.
           "Malahit RX" is the same signal already demodulated, 48 kHz mono.

Requires: numpy, sounddevice, pyserial.
"""

import argparse
import re
import sys
import threading
import time
import wave

import numpy as np
import serial
from serial.tools import list_ports
import sounddevice as sd

BAUD = 115200
IQ_RATE = 192000
AUDIO_RATE = 48000
USB_VID = 0xFFFF
USB_PID = 0x0737

MODE_NAMES = {
    1: "LSB", 2: "USB", 3: "CW", 4: "FM", 5: "AM", 6: "FSK", 7: "CW-R",
    9: "CW-R", 0: "DSB",
}


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def find_com_port():
    """Locate the Malahit CAT port by its USB VID:PID."""
    for p in list_ports.comports():
        if p.vid == USB_VID and p.pid == USB_PID:
            return p.device
    return None


def find_audio(fragment, need_input=True):
    """Locate a Malahit audio device index by name fragment."""
    for index, dev in enumerate(sd.query_devices()):
        if fragment.lower() not in dev["name"].lower():
            continue
        if need_input and dev["max_input_channels"] < 1:
            continue
        if not need_input and dev["max_output_channels"] < 1:
            continue
        return index
    return None


# --------------------------------------------------------------------------
# CAT
# --------------------------------------------------------------------------

class Cat:
    def __init__(self, port=None, timeout=0.5):
        self.port = port or find_com_port()
        if not self.port:
            raise RuntimeError("Malahit CAT port not found (USB VID_FFFF&PID_0737)")
        self.ser = serial.Serial(self.port, BAUD, timeout=timeout)
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def query(self, cmd, wait=0.25):
        self.ser.reset_input_buffer()
        self.ser.write(cmd.encode())
        time.sleep(wait)
        return self.ser.read(256).decode("ascii", "replace").strip()

    def write(self, cmd, wait=0.35):
        self.ser.reset_input_buffer()
        self.ser.write(cmd.encode())
        time.sleep(wait)
        self.ser.read(256)

    def set_freq(self, hz):
        self.write("FA%011d;" % hz)

    def get_freq(self):
        r = self.query("FA;")
        m = re.match(r"FA(\d{11});", r)
        return int(m.group(1)) if m else None

    def set_mode(self, mode):
        self.write("MD%d;" % mode)

    def get_mode(self):
        r = self.query("MD;")
        m = re.match(r"MD(\d);", r)
        return int(m.group(1)) if m else None

    def get_smeter(self):
        r = self.query("SM0;")
        m = re.match(r"SM(\d+);", r)
        return int(m.group(1)) if m else None


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------

class IqStream:
    """Continuous I/Q capture.

    WDM-KS (the host API the Malahit exposes) does not support PortAudio's
    blocking API, so samples are collected from the stream callback instead.
    """

    def __init__(self, device, rate=IQ_RATE):
        self.rate = rate
        self._chunks = []
        self._lock = threading.Lock()
        self._stream = sd.InputStream(device=device, channels=2, samplerate=rate,
                                      dtype="int16", callback=self._callback)

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            self._chunks.append(indata.copy())

    def __enter__(self):
        self._stream.start()
        return self

    def __exit__(self, *exc):
        self._stream.stop()
        self._stream.close()

    def _drain(self):
        with self._lock:
            chunks, self._chunks = self._chunks, []
        return chunks

    def flush(self):
        self._drain()

    def read(self, frames, timeout=10.0):
        """Collect exactly `frames` stereo samples."""
        deadline = time.monotonic() + timeout
        out = []
        got = 0
        while got < frames:
            if time.monotonic() > deadline:
                raise RuntimeError("audio capture timed out")
            time.sleep(0.005)
            for chunk in self._drain():
                out.append(chunk)
                got += len(chunk)
        data = np.concatenate(out, axis=0) if out else np.zeros((0, 2), np.int16)
        return data[:frames]


def capture_iq(device, seconds, rate=IQ_RATE):
    """Capture raw I/Q as an int16 array of shape (frames, 2)."""
    frames = int(rate * seconds)
    with IqStream(device, rate) as stream:
        return stream.read(frames)


def write_iq_wav(path, iq, rate=IQ_RATE):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.ascontiguousarray(iq, dtype=np.int16).tobytes())


def read_iq_wav(path):
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 2:
            raise RuntimeError("%s is not a stereo I/Q file" % path)
        rate = w.getframerate()
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return raw.reshape(-1, 2), rate


def iq_rms_dbfs(iq):
    x = iq.astype(np.float64) / 32768.0
    power = x[:, 0] ** 2 + x[:, 1] ** 2
    return 20 * np.log10(np.sqrt(power.mean()) + 1e-12)


# --------------------------------------------------------------------------
# DSP
# --------------------------------------------------------------------------

def lowpass(x, fs, cutoff, taps=129):
    n = np.arange(taps) - (taps - 1) / 2.0
    h = np.sinc(2.0 * cutoff / fs * n) * np.blackman(taps)
    h /= h.sum()
    return np.convolve(x, h, mode="same")


def fm_demod(iq, rate, out_rate=AUDIO_RATE, audio_bw=15000):
    """Discriminate stereo I/Q into mono audio at out_rate."""
    x = iq.astype(np.float64) / 32768.0
    z = x[:, 0] + 1j * x[:, 1]
    d = np.angle(z[1:] * np.conj(z[:-1]))

    factor = max(1, int(round(rate / out_rate)))
    d = lowpass(d, rate, audio_bw)
    d = d[: len(d) // factor * factor].reshape(-1, factor).mean(axis=1)
    d -= d.mean()

    peak = np.abs(d).max()
    if peak > 0:
        d = d / peak * 0.8
    return (d * 32767).astype(np.int16), rate // factor


def write_mono_wav(path, samples, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.ascontiguousarray(samples, dtype=np.int16).tobytes())


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def parse_freq(text):
    """Accept 100500000, 100.5M, 7100k, 145.5MHz."""
    s = str(text).strip().lower().replace("hz", "").replace(" ", "")
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)([gmk]?)", s)
    if not m:
        raise argparse.ArgumentTypeError("cannot parse frequency: %r" % text)
    value, suffix = float(m.group(1)), m.group(2)
    if suffix == "g":
        value *= 1e9
    elif suffix == "m":
        value *= 1e6
    elif suffix == "k":
        value *= 1e3
    return int(round(value))


def format_freq(hz):
    if hz >= 1e6:
        return "%.6f MHz" % (hz / 1e6)
    if hz >= 1e3:
        return "%.3f kHz" % (hz / 1e3)
    return "%d Hz" % hz


def resolve_iq_device(explicit=None):
    if explicit is not None:
        return explicit
    dev = find_audio("Malahit IQ")
    if dev is None:
        raise RuntimeError('audio input "Malahit IQ" not found')
    return dev


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_info(args):
    port = find_com_port()
    print("CAT port      :", port or "not found")
    if port:
        with Cat(port) as cat:
            print("CAT identity  :", cat.query("ID;"))
            hz = cat.get_freq()
            mode = cat.get_mode()
            print("frequency     :", format_freq(hz) if hz else "?")
            print("mode          :", MODE_NAMES.get(mode, mode))
            print("S-meter       :", cat.get_smeter())

    for label, fragment, need_input in (
        ("IQ input      ", "Malahit IQ", True),
        ("RX audio input", "Malahit RX", True),
        ("headphone out ", "Malahit Headphone", False),
    ):
        idx = find_audio(fragment, need_input)
        if idx is None:
            print(label + ":", "not found")
            continue
        d = sd.query_devices(idx)
        print(label + ":", "[%d] %s  ch=%d  sr=%.0f" % (
            idx, d["name"], d["max_input_channels"] or d["max_output_channels"],
            d["default_samplerate"]))


def cmd_get(args):
    with Cat(args.port) as cat:
        hz = cat.get_freq()
        mode = cat.get_mode()
        print("frequency:", format_freq(hz) if hz else "?")
        print("mode     :", MODE_NAMES.get(mode, mode))
        print("S-meter  :", cat.get_smeter())


def cmd_tune(args):
    with Cat(args.port) as cat:
        cat.set_freq(args.freq)
        if args.mode is not None:
            cat.set_mode(args.mode)
        time.sleep(0.2)
        print("tuned to", format_freq(cat.get_freq()))


def cmd_scan(args):
    device = resolve_iq_device(args.device)
    span = int(args.stop - args.start)
    if span <= 0:
        raise SystemExit("stop must be above start")
    steps = span // args.step + 1

    with Cat(args.port) as cat, IqStream(device) as stream:
        print("%-14s %10s  %s" % ("frequency", "level", "signal"))
        best = (-999.0, None)
        for i in range(steps):
            hz = args.start + i * args.step
            cat.set_freq(hz)
            time.sleep(args.settle)
            stream.flush()
            level = iq_rms_dbfs(stream.read(int(IQ_RATE * args.seconds)))
            bar = "#" * max(0, int((level + 80) / 2))
            print("%-14s %8.1f dB  %s" % (format_freq(hz), level, bar))
            if level > best[0]:
                best = (level, hz)

    if best[1]:
        print("\nstrongest: %s (%.1f dBFS)" % (format_freq(best[1]), best[0]))


def cmd_record(args):
    device = resolve_iq_device(args.device)
    if args.freq:
        with Cat(args.port) as cat:
            cat.set_freq(args.freq)
            time.sleep(args.settle)
    print("recording %.1f s of I/Q at %d Hz -> %s" % (args.seconds, args.rate, args.out))
    iq = capture_iq(device, args.seconds, args.rate)
    write_iq_wav(args.out, iq, args.rate)
    print("saved %d frames (%.2f s), level %.1f dBFS" % (
        len(iq), len(iq) / args.rate, iq_rms_dbfs(iq)))


def cmd_demod(args):
    iq, rate = read_iq_wav(args.input)
    audio, out_rate = fm_demod(iq, rate, args.rate_out)
    write_mono_wav(args.out, audio, out_rate)
    print("demodulated %s (%d Hz I/Q, %.2f s) -> %s (%d Hz, %d samples)" % (
        args.input, rate, len(iq) / rate, args.out, out_rate, len(audio)))


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Malahit DSP3 control and raw I/Q capture.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  malahit.py info
  malahit.py tune 100.5M
  malahit.py scan 87.5M 108M --step 100k
  malahit.py record 100.5M fm.wav --seconds 10
  malahit.py demod fm.wav audio.wav
""")
    p.add_argument("--port", help="CAT serial port (default: auto-detect)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show CAT port, identity and audio devices")

    sub.add_parser("get", help="read frequency, mode and S-meter")

    t = sub.add_parser("tune", help="set frequency")
    t.add_argument("freq", type=parse_freq, help="e.g. 100.5M, 7100k, 145500000")
    t.add_argument("--mode", type=int, help="Kenwood mode code: 1 LSB, 2 USB, 4 FM, 5 AM")

    s = sub.add_parser("scan", help="scan a range and report I/Q level")
    s.add_argument("start", type=parse_freq)
    s.add_argument("stop", type=parse_freq)
    s.add_argument("--step", type=parse_freq, default=100000)
    s.add_argument("--seconds", type=float, default=0.15, help="dwell per step")
    s.add_argument("--settle", type=float, default=0.35, help="wait after retune")
    s.add_argument("--device", type=int, help="IQ input device index")

    r = sub.add_parser("record", help="record raw I/Q to a stereo WAV")
    r.add_argument("out")
    r.add_argument("freq", nargs="?", type=parse_freq, help="optional frequency to tune first")
    r.add_argument("--seconds", type=float, default=10.0)
    r.add_argument("--rate", type=int, default=IQ_RATE)
    r.add_argument("--settle", type=float, default=0.5)
    r.add_argument("--device", type=int, help="IQ input device index")

    d = sub.add_parser("demod", help="FM-demodulate an I/Q WAV into audio")
    d.add_argument("input")
    d.add_argument("out")
    d.add_argument("--rate-out", type=int, default=AUDIO_RATE)

    args = p.parse_args(argv)
    handler = {
        "info": cmd_info,
        "get": cmd_get,
        "tune": cmd_tune,
        "scan": cmd_scan,
        "record": cmd_record,
        "demod": cmd_demod,
    }[args.command]
    try:
        handler(args)
    except (RuntimeError, OSError) as exc:
        print("error:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import malahit


class ParseFreqTests(unittest.TestCase):
    def test_plain_hz(self):
        self.assertEqual(malahit.parse_freq("100500000"), 100500000)

    def test_suffixes(self):
        self.assertEqual(malahit.parse_freq("100.5M"), 100500000)
        self.assertEqual(malahit.parse_freq("7100k"), 7100000)
        self.assertEqual(malahit.parse_freq("145.5MHz"), 145500000)
        self.assertEqual(malahit.parse_freq("1g"), 1000000000)

    def test_rejects_garbage(self):
        with self.assertRaises(Exception):
            malahit.parse_freq("abc")

    def test_format_roundtrip(self):
        self.assertEqual(malahit.format_freq(100500000), "100.500000 MHz")
        self.assertEqual(malahit.format_freq(7100000), "7.100000 MHz")


class IqWavTests(unittest.TestCase):
    def test_write_read_roundtrip(self):
        frames = 1000
        iq = np.zeros((frames, 2), dtype=np.int16)
        iq[:, 0] = np.arange(frames)
        iq[:, 1] = -np.arange(frames)

        path = os.path.join(tempfile.mkdtemp(), "iq.wav")
        malahit.write_iq_wav(path, iq, 192000)
        back, rate = malahit.read_iq_wav(path)

        self.assertEqual(rate, 192000)
        self.assertEqual(back.shape, (frames, 2))
        np.testing.assert_array_equal(back, iq)

    def test_rejects_mono(self):
        import wave

        path = os.path.join(tempfile.mkdtemp(), "mono.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"\0\0" * 100)
        with self.assertRaises(RuntimeError):
            malahit.read_iq_wav(path)


class LevelTests(unittest.TestCase):
    def test_silence_is_very_low(self):
        self.assertLess(malahit.iq_rms_dbfs(np.zeros((100, 2), np.int16)), -100)

    def test_full_scale_is_plus_3_db(self):
        # I and Q both at full scale give |z| = sqrt(2), i.e. +3.01 dB
        iq = np.full((100, 2), 32767, dtype=np.int16)
        self.assertAlmostEqual(malahit.iq_rms_dbfs(iq), 3.01, delta=0.1)


class FmDemodTests(unittest.TestCase):
    def test_recovers_tone_from_synthetic_iq(self):
        rate = 192000
        tone = 1000.0
        n = rate  # 1 second
        t = np.arange(n) / rate

        # Frequency-modulate a carrier: phase integral of the modulating tone.
        deviation = 2000.0
        phase = 2 * np.pi * deviation / tone * np.sin(2 * np.pi * tone * t)
        z = np.exp(1j * phase)

        iq = np.empty((n, 2), dtype=np.int16)
        iq[:, 0] = np.clip(z.real * 20000, -32768, 32767).astype(np.int16)
        iq[:, 1] = np.clip(z.imag * 20000, -32768, 32767).astype(np.int16)

        audio, out_rate = malahit.fm_demod(iq, rate, 48000)

        self.assertEqual(out_rate, 48000)
        self.assertGreater(len(audio), 47000)

        spectrum = np.abs(np.fft.rfft(audio.astype(np.float64)))
        freqs = np.fft.rfftfreq(len(audio), 1 / out_rate)
        peak = freqs[np.argmax(spectrum)]
        self.assertAlmostEqual(peak, tone, delta=20.0)


if __name__ == "__main__":
    unittest.main()

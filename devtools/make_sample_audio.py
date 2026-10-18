"""Create a silent WAV file for trying the upload flow (handy with the demo server).

    python devtools/make_sample_audio.py sample.wav 270
"""

import sys
import wave


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "sample.wav"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    rate = 8000
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * rate * seconds)
    print(f"Wrote {path} ({seconds}s)")


if __name__ == "__main__":
    main()

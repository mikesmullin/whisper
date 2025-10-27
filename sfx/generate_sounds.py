#!/usr/bin/env python3
"""
Generate default beep sounds for whisper voice keyboard
"""

import numpy as np
import wave
from pathlib import Path


def generate_beep(filename, frequency=800, duration=0.1, sample_rate=44100):
    """
    Generate a simple beep sound
    
    Args:
        filename: Output WAV filename
        frequency: Beep frequency in Hz
        duration: Duration in seconds
        sample_rate: Audio sample rate
    """
    # Generate sine wave
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * frequency * t)
    
    # Apply fade in/out to avoid clicks
    fade_samples = int(0.01 * sample_rate)
    if fade_samples > 0:
        audio[:fade_samples] *= np.linspace(0, 1, fade_samples)
        audio[-fade_samples:] *= np.linspace(1, 0, fade_samples)
    
    # Convert to 16-bit PCM
    audio = (audio * 32767).astype(np.int16)
    
    # Write WAV file
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 2 bytes = 16 bits
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())
    
    print(f"✓ Generated {filename} ({frequency}Hz, {duration}s)")


def main():
    """Generate default sound effects"""
    sfx_dir = Path(__file__).parent
    
    print("Generating default sound effects...")
    print()
    
    # High beep for "listening started"
    generate_beep(
        str(sfx_dir / 'on.wav'),
        frequency=880,  # A5 note
        duration=0.08
    )
    
    # Low beep for "listening stopped"
    generate_beep(
        str(sfx_dir / 'off.wav'),
        frequency=440,  # A4 note
        duration=0.08
    )
    
    print()
    print("✓ Default sound effects generated")
    print("  You can replace these files with your own .wav files")


if __name__ == '__main__':
    main()

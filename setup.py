#!/usr/bin/env python3
"""Setup script for Whisper tool."""

from setuptools import setup, find_packages
from pathlib import Path

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
if requirements_file.exists():
    with open(requirements_file) as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
else:
    requirements = []

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
if readme_file.exists():
    with open(readme_file, encoding="utf-8") as f:
        long_description = f.read()
else:
    long_description = "A CLI tool for real-time transcription with speaker identification"

setup(
    name="whisper",
    version="1.0.0",
    description="Cross-platform voice keyboard with speech-to-text typing",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Mike Smullin",
    author_email="mike@smullindesign.com",
    url="https://github.com/mikesmullin/whisper",
    packages=find_packages(include=["lib*"]),
    py_modules=["whisper"],  # Include whisper.py as a module
    install_requires=requirements,
    python_requires=">=3.11",
    entry_points={
        "console_scripts": [
            "whisper=whisper:main",  # Creates 'whisper' command that calls main() from whisper.py
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
        "Topic :: Utilities",
    ],
)

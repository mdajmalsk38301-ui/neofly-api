#!/usr/bin/env bash
# Install Python packages
pip install -r requirements.txt

# Download and install a standalone version of FFmpeg
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar -xf ffmpeg-release-amd64-static.tar.xz
mkdir -p bin
mv ffmpeg-*-static/ffmpeg bin/
mv ffmpeg-*-static/ffprobe bin/

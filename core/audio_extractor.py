import os
import subprocess
import shutil
import numpy as np
from typing import Tuple, Optional


def check_ffmpeg() -> str:
    """Check if ffmpeg executable is available on system PATH."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError(
            "FFmpeg not found! Please ensure FFmpeg is installed and added to your system PATH."
        )
    return ffmpeg_path


def get_media_duration(file_path: str) -> Optional[float]:
    """Get the duration of a media file in seconds using ffprobe."""
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        return None
    try:
        cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return None


def extract_audio_stream(
    media_path: str,
    sample_rate: int = 16000,
    max_duration: Optional[float] = None
) -> Tuple[np.ndarray, int, float]:
    """
    Extract audio from video/audio file directly into memory as 16-bit mono PCM.
    
    Args:
        media_path: Path to video (e.g. .mp4, .mkv, .avi) or audio file.
        sample_rate: Target audio sample rate in Hz (default: 16000, standard for VAD).
        max_duration: Optional maximum duration in seconds to read (useful for testing).
        
    Returns:
        (pcm_data, sample_rate, duration_sec):
            pcm_data: 1D numpy array of dtype int16
            sample_rate: 16000
            duration_sec: total duration in seconds
    """
    if not os.path.isfile(media_path):
        raise FileNotFoundError(f"Media file not found: {media_path}")

    check_ffmpeg()

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v", "error",
        "-i", media_path,
    ]

    if max_duration is not None and max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    # Output format: raw 16-bit signed PCM, 1 channel (mono), 16000Hz
    cmd.extend([
        "-vn",          # disable video
        "-sn",          # disable subtitle streams
        "-dn",          # disable data streams
        "-f", "s16le",  # format: raw PCM 16-bit little endian
        "-acodec", "pcm_s16le",
        "-ac", "1",     # mono
        "-ar", str(sample_rate),
        "pipe:1"        # stream to stdout
    ])

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    stdout_data, stderr_data = process.communicate()

    if process.returncode != 0:
        err_msg = stderr_data.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg audio extraction failed (code {process.returncode}):\n{err_msg}")

    # Convert raw bytes to int16 numpy array
    pcm_data = np.frombuffer(stdout_data, dtype=np.int16)
    duration_sec = len(pcm_data) / float(sample_rate)

    return pcm_data, sample_rate, duration_sec

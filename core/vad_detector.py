import numpy as np
import webrtcvad
from typing import Optional


def compute_vad_mask(
    pcm_data: np.ndarray,
    sample_rate: int = 16000,
    frame_ms: int = 20,
    aggressiveness: int = 2,
    smooth_window_ms: int = 300,
    target_fps: int = 100,
) -> np.ndarray:
    """
    Compute speech activity mask from 16-bit mono PCM audio using WebRTC VAD.
    
    Args:
        pcm_data: 1D numpy array of int16 samples.
        sample_rate: Must be 8000, 16000, 32000, or 48000 Hz (default 16000).
        frame_ms: Frame length in ms for WebRTC VAD. Must be 10, 20, or 30 ms.
        aggressiveness: VAD mode (0 = least aggressive, 3 = most aggressive filtering).
        smooth_window_ms: Hangover smoothing window in ms to merge micro-pauses between words.
        target_fps: Output time-series sampling rate in Hz (default: 100 Hz, 10ms resolution).
        
    Returns:
        1D float32 numpy array of speech activity (0.0 = silence/background, 1.0 = speech)
        at `target_fps` rate.
    """
    if sample_rate not in (8000, 16000, 32000, 48000):
        raise ValueError(f"WebRTC VAD only supports 8000, 16000, 32000, 48000 Hz, got {sample_rate}")
    if frame_ms not in (10, 20, 30):
        raise ValueError(f"WebRTC VAD only supports frame_ms of 10, 20, or 30, got {frame_ms}")

    vad = webrtcvad.Vad(int(aggressiveness))

    samples_per_frame = int(sample_rate * (frame_ms / 1000.0))
    bytes_per_frame = samples_per_frame * 2  # 16-bit = 2 bytes per sample

    total_samples = len(pcm_data)
    num_frames = total_samples // samples_per_frame
    if num_frames == 0:
        return np.zeros(0, dtype=np.float32)

    # Convert pcm_data buffer to bytes for WebRTC VAD
    raw_bytes = pcm_data[: num_frames * samples_per_frame].tobytes()

    is_speech_list = []
    for i in range(num_frames):
        start_byte = i * bytes_per_frame
        frame = raw_bytes[start_byte : start_byte + bytes_per_frame]
        try:
            is_speech = vad.is_speech(frame, sample_rate)
        except Exception:
            is_speech = False
        is_speech_list.append(1.0 if is_speech else 0.0)

    vad_frames = np.array(is_speech_list, dtype=np.float32)
    vad_fps = 1000.0 / frame_ms

    # Apply morphological closing to bridge micro-pauses between words/syllables
    # binary_closing fills internal gaps without expanding the outer start/end timestamps.
    if smooth_window_ms > 0:
        window_size = max(1, int((smooth_window_ms / 1000.0) * vad_fps))
        from scipy.ndimage import binary_closing
        smoothed = binary_closing(vad_frames > 0.5, structure=np.ones(window_size)).astype(np.float32)
    else:
        smoothed = vad_frames

    # Resample to target_fps (typically 100Hz = 10ms per sample)
    total_duration_sec = total_samples / float(sample_rate)
    target_length = int(np.ceil(total_duration_sec * target_fps))

    if len(smoothed) == 0:
        return np.zeros(target_length, dtype=np.float32)

    orig_times = np.linspace(0, total_duration_sec, len(smoothed), endpoint=False)
    target_times = np.linspace(0, total_duration_sec, target_length, endpoint=False)
    
    resampled_mask = np.interp(target_times, orig_times, smoothed)
    return (resampled_mask >= 0.5).astype(np.float32)

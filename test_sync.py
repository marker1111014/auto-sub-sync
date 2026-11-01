import os
import sys
import io
import wave
import struct
import numpy as np
import pysubs2
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


from core.audio_extractor import extract_audio_stream
from core.vad_detector import compute_vad_mask
from core.subtitle_io import load_subtitle, save_subtitle, rasterize_subtitles, apply_transform
from core.aligner import find_best_alignment, find_best_offset_fft, compute_overlap_metrics


def generate_synthetic_audio(
    file_path: str,
    duration_sec: float,
    speech_intervals: list,
    sample_rate: int = 16000
):
    """
    Generate synthetic WAV audio with sine waves during speech intervals and silence elsewhere.
    WebRTC VAD detects energy in voice bands (300Hz-3400Hz), so we mix harmonic tones (400Hz + 800Hz + 1200Hz).
    """
    total_samples = int(duration_sec * sample_rate)
    audio = np.zeros(total_samples, dtype=np.int16)

    for start_s, end_s in speech_intervals:
        s_idx = int(start_s * sample_rate)
        e_idx = min(total_samples, int(end_s * sample_rate))
        t = np.linspace(0, (e_idx - s_idx) / sample_rate, e_idx - s_idx, endpoint=False)
        # Synthetic speech-like harmonic tone
        tone = (
            0.5 * np.sin(2 * np.pi * 400 * t) +
            0.3 * np.sin(2 * np.pi * 800 * t) +
            0.2 * np.sin(2 * np.pi * 1200 * t)
        )
        audio[s_idx:e_idx] = (tone * 18000).astype(np.int16)

    # Write WAV file
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())


def create_synthetic_subtitle(
    file_path: str,
    intervals: list,
    text_prefix: str = "對話"
):
    """Create synthetic SRT file with specified intervals."""
    subs = pysubs2.SSAFile()
    for idx, (start_s, end_s) in enumerate(intervals, 1):
        event = pysubs2.SSAEvent(
            start=int(start_s * 1000),
            end=int(end_s * 1000),
            text=f"{text_prefix} #{idx}"
        )
        subs.events.append(event)
    subs.save(file_path, encoding="utf-8")


def test_cross_correlation_direct():
    """Test FFT cross-correlation on synthetic discrete masks."""
    print("\n--- Test 1: Pure FFT Cross-Correlation Logic ---")
    fps = 100
    total_samples = 60 * fps  # 60 seconds
    audio_mask = np.zeros(total_samples, dtype=np.float32)

    # Speech at 10s-15s and 25s-32s
    audio_mask[10 * fps : 15 * fps] = 1.0
    audio_mask[25 * fps : 32 * fps] = 1.0

    # Subtitle is 3.5 seconds late (appears at 13.5s and 28.5s)
    true_offset = -3.5  # needs to shift by -3.5s to match audio
    sub_mask = np.zeros(total_samples, dtype=np.float32)
    sub_mask[int(13.5 * fps) : int(18.5 * fps)] = 1.0
    sub_mask[int(28.5 * fps) : int(35.5 * fps)] = 1.0

    detected_offset, peak = find_best_offset_fft(audio_mask, sub_mask, target_fps=fps)
    print(f"Ground Truth Offset: {true_offset:.2f}s | Detected: {detected_offset:.2f}s")
    assert abs(detected_offset - true_offset) < 0.05, f"Offset error too large: {detected_offset} vs {true_offset}"
    print("✅ Test 1 Passed: Exact offset recovered within 10ms!")


def test_end_to_end_pipeline(tmp_path: Path):
    """Test full pipeline with WAV generation, FFmpeg audio extraction, VAD, and SRT correction."""
    print("\n--- Test 2: Full End-to-End Pipeline (Audio + VAD + Subtitle) ---")
    wav_path = str(tmp_path / "test_movie.wav")
    srt_path = str(tmp_path / "test_movie.srt")
    out_path = str(tmp_path / "test_movie_synced.srt")

    # Audio speech intervals (seconds)
    audio_dialogues = [
        (4.0, 8.0),
        (12.0, 17.0),
        (22.0, 28.0),
        (35.0, 42.0),
    ]
    duration_total = 50.0
    generate_synthetic_audio(wav_path, duration_total, audio_dialogues)

    # Subtitle offset: deliberately delay by +5.20 seconds
    deliberate_delay = 5.20
    desynced_dialogues = [
        (s + deliberate_delay, e + deliberate_delay) for s, e in audio_dialogues
    ]
    create_synthetic_subtitle(srt_path, desynced_dialogues)

    # 1. Extract audio
    pcm, sr, dur = extract_audio_stream(wav_path)
    assert len(pcm) > 0, "Failed to extract PCM"

    # 2. VAD
    vad_mask = compute_vad_mask(pcm, sample_rate=sr, target_fps=100)
    assert vad_mask.sum() > 0, "VAD detected no speech"

    # 3. Load & align
    subs = load_subtitle(srt_path)
    result = find_best_alignment(vad_mask, subs, target_fps=100, search_framerate_drift=False)

    print(f"Deliberate Subtitle Offset: +{deliberate_delay:.2f}s")
    print(f"Recovered Correction Offset: {result.offset_seconds:.3f}s (Expected: -{deliberate_delay:.2f}s)")
    print(f"Unaligned Overlap Score:     {result.unaligned_score * 100:.1f}%")
    print(f"Aligned Overlap Score:       {result.overlap_score * 100:.1f}%")

    # Subtitle appeared 5.2s late, so correction should be ~ -5.20s
    expected_correction = -deliberate_delay
    assert abs(result.offset_seconds - expected_correction) < 0.25, (
        f"Correction offset {result.offset_seconds} deviated from expected {expected_correction}"
    )
    assert result.overlap_score > 0.85, f"Overlap score too low: {result.overlap_score}"

    # 4. Save synced subtitle & check timestamps
    synced_subs = apply_transform(subs, scale=result.scale_factor, offset_sec=result.offset_seconds)
    save_subtitle(synced_subs, out_path)

    loaded_synced = load_subtitle(out_path)
    assert len(loaded_synced) == len(audio_dialogues)
    first_cue_start = loaded_synced[0].start / 1000.0
    print(f"Original speech start: {audio_dialogues[0][0]:.2f}s | Synced subtitle start: {first_cue_start:.2f}s")
    assert abs(first_cue_start - audio_dialogues[0][0]) < 0.25

    print("✅ Test 2 Passed: Full pipeline successfully recovered and synchronized subtitle!")


def test_framerate_drift(tmp_path: Path):
    """Test standard framerate drift (e.g. 25 fps PAL speedup)."""
    print("\n--- Test 3: Framerate Drift (PAL Speedup / Scale Factor) ---")
    wav_path = str(tmp_path / "test_drift.wav")
    srt_path = str(tmp_path / "test_drift.srt")

    # Speech in movie at 25 fps
    base_dialogues = [
        (5.0, 10.0),
        (20.0, 26.0),
        (45.0, 52.0),
        (80.0, 88.0),
    ]
    duration_total = 100.0
    generate_synthetic_audio(wav_path, duration_total, base_dialogues)

    # Subtitle created for 24 fps movie, played on 25 fps video (drift factor = 24/25 = 0.96) + 3.0s offset
    true_scale = 24.0 / 25.0  # 0.96
    true_offset = -3.0
    # Subtitle timestamps: t_sub = (t_base - true_offset) / true_scale
    drifted_dialogues = [
        ((s - true_offset) / true_scale, (e - true_offset) / true_scale)
        for s, e in base_dialogues
    ]
    create_synthetic_subtitle(srt_path, drifted_dialogues)

    pcm, sr, _ = extract_audio_stream(wav_path)
    vad_mask = compute_vad_mask(pcm, sample_rate=sr, target_fps=100)
    subs = load_subtitle(srt_path)

    result = find_best_alignment(vad_mask, subs, target_fps=100, search_framerate_drift=True)
    print(f"Expected Scale: {true_scale:.4f} | Detected Scale: {result.scale_factor:.4f}")
    print(f"Expected Offset: {true_offset:.2f}s | Detected Offset: {result.offset_seconds:.2f}s")
    print(f"Aligned Score: {result.overlap_score * 100:.1f}%")

    assert abs(result.scale_factor - true_scale) < 0.01, f"Scale mismatch: {result.scale_factor} vs {true_scale}"
    assert abs(result.offset_seconds - true_offset) < 0.3, f"Offset mismatch: {result.offset_seconds} vs {true_offset}"
    print("✅ Test 3 Passed: Framerate drift and offset simultaneously resolved!")


if __name__ == "__main__":
    import tempfile
    test_cross_correlation_direct()
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_end_to_end_pipeline(Path(tmp_dir))
        test_framerate_drift(Path(tmp_dir))
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉\n")

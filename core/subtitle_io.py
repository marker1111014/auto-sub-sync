import os
import copy
import chardet
import numpy as np
import pysubs2
from typing import Optional, List, Tuple


def detect_file_encoding(file_path: str) -> str:
    """Detect file encoding using chardet with fallbacks."""
    with open(file_path, "rb") as f:
        raw = f.read(50000)
    res = chardet.detect(raw)
    encoding = res.get("encoding")
    if not encoding or res.get("confidence", 0) < 0.6:
        # Common subtitle encodings fallback
        for enc in ["utf-8-sig", "utf-8", "gbk", "big5", "cp1252", "shift_jis"]:
            try:
                raw.decode(enc)
                return enc
            except Exception:
                continue
        return "utf-8"
    return encoding


def load_subtitle(file_path: str) -> pysubs2.SSAFile:
    """
    Load a subtitle file (SRT, ASS, SSA, VTT) with robust encoding detection.
    
    Args:
        file_path: Path to subtitle file.
        
    Returns:
        pysubs2.SSAFile instance.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Subtitle file not found: {file_path}")

    # Try standard load first
    try:
        return pysubs2.load(file_path)
    except Exception:
        # Fall back to detected encoding
        enc = detect_file_encoding(file_path)
        try:
            return pysubs2.load(file_path, encoding=enc)
        except Exception as e:
            # Last ditch attempt with utf-8 ignoring errors
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return pysubs2.SSAFile.from_string(content)


def save_subtitle(
    subs: pysubs2.SSAFile,
    output_path: str,
    format_name: Optional[str] = None
) -> None:
    """
    Save subtitle file with UTF-8 encoding.
    
    Args:
        subs: pysubs2.SSAFile instance.
        output_path: Target save path.
        format_name: Optional format ('srt', 'ass', 'vtt'). Inferred from extension if None.
    """
    subs.save(output_path, format_=format_name, encoding="utf-8")


def get_subtitle_intervals(subs: pysubs2.SSAFile) -> List[Tuple[float, float]]:
    """
    Extract (start_sec, end_sec) intervals for all dialogue events.
    """
    intervals = []
    for event in subs:
        if event.is_comment:
            continue
        # start and end are in milliseconds
        start_sec = max(0.0, event.start / 1000.0)
        end_sec = max(start_sec, event.end / 1000.0)
        if end_sec > start_sec:
            intervals.append((start_sec, end_sec))
    return intervals


def rasterize_subtitles(
    subs: pysubs2.SSAFile,
    target_length: int,
    target_fps: int = 100,
    scale: float = 1.0,
    offset_sec: float = 0.0,
) -> np.ndarray:
    """
    Rasterize subtitle cues into a 1D binary activity mask at `target_fps`.
    
    Args:
        subs: Subtitle object.
        target_length: Length of the output array in samples.
        target_fps: Sampling frequency (default 100 Hz).
        scale: Optional time scaling factor to apply during rasterization.
        offset_sec: Optional time offset in seconds to apply during rasterization.
        
    Returns:
        1D float32 numpy array (0.0 = no subtitle, 1.0 = subtitle displayed).
    """
    mask = np.zeros(target_length, dtype=np.float32)
    intervals = get_subtitle_intervals(subs)

    for start_sec, end_sec in intervals:
        t_start = (start_sec * scale) + offset_sec
        t_end = (end_sec * scale) + offset_sec

        if t_end <= 0:
            continue

        idx_start = max(0, int(round(t_start * target_fps)))
        idx_end = min(target_length, int(round(t_end * target_fps)))

        if idx_end > idx_start:
            mask[idx_start:idx_end] = 1.0

    return mask


def apply_transform(
    subs: pysubs2.SSAFile,
    scale: float = 1.0,
    offset_sec: float = 0.0,
) -> pysubs2.SSAFile:
    """
    Apply linear transformation to all subtitle event timestamps:
        t_new = t_old * scale + offset_sec
        
    Args:
        subs: Source subtitle object.
        scale: Scaling factor (e.g. 1.0 for pure shift, or 25/24 for PAL speedup).
        offset_sec: Shift in seconds (+ means delay subtitle, - means advance subtitle).
        
    Returns:
        A new transformed pysubs2.SSAFile instance.
    """
    offset_ms = int(round(offset_sec * 1000.0))
    new_subs = copy.deepcopy(subs)

    valid_events = []
    for event in new_subs.events:
        new_start = int(round(event.start * scale)) + offset_ms
        new_end = int(round(event.end * scale)) + offset_ms

        # Discard cues that end before time 0
        if new_end <= 0:
            continue

        event.start = max(0, new_start)
        event.end = max(event.start + 100, new_end)
        valid_events.append(event)

    new_subs.events = valid_events
    return new_subs

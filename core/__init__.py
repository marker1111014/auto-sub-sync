"""
Core modules for Movie Subtitle Fix.
Provides audio extraction, VAD speech detection, subtitle IO, and cross-correlation alignment.
"""

from .audio_extractor import extract_audio_stream
from .vad_detector import compute_vad_mask
from .subtitle_io import load_subtitle, save_subtitle, rasterize_subtitles, apply_transform
from .aligner import find_best_alignment, AlignmentResult

__all__ = [
    "extract_audio_stream",
    "compute_vad_mask",
    "load_subtitle",
    "save_subtitle",
    "rasterize_subtitles",
    "apply_transform",
    "find_best_alignment",
    "AlignmentResult",
]

import numpy as np
import scipy.signal
from dataclasses import dataclass
from typing import List, Tuple, Optional
import pysubs2

from .subtitle_io import rasterize_subtitles, apply_transform


@dataclass
class AlignmentResult:
    offset_seconds: float
    scale_factor: float
    overlap_score: float  # F1 score or normalized correlation (0.0 to 1.0)
    precision: float      # % of subtitle time that coincides with speech
    recall: float         # % of speech time covered by subtitles
    iou: float            # Intersection over union
    unaligned_score: float # Overlap score before synchronization


STANDARD_FPS_RATIOS = [
    1.0,                       # Exact match / No framerate drift
    24.0 / 23.976,             # Film to NTSC (~1.001001)
    23.976 / 24.0,             # NTSC to Film (~0.999000)
    25.0 / 24.0,               # Film to PAL speedup (~1.041667)
    24.0 / 25.0,               # PAL to Film slowdown (0.960000)
    25.0 / 23.976,             # NTSC to PAL speedup (~1.042709)
    23.976 / 25.0,             # PAL to NTSC slowdown (~0.959040)
]


def compute_overlap_metrics(
    vad_mask: np.ndarray,
    sub_mask: np.ndarray
) -> Tuple[float, float, float, float]:
    """
    Compute overlap metrics between audio speech mask and subtitle mask.
    
    Returns:
        (f1_score, precision, recall, iou)
    """
    length = min(len(vad_mask), len(sub_mask))
    if length == 0:
        return 0.0, 0.0, 0.0, 0.0

    v = vad_mask[:length] > 0.5
    s = sub_mask[:length] > 0.5

    intersection = np.logical_and(v, s).sum()
    sum_s = s.sum()
    sum_v = v.sum()
    union = np.logical_or(v, s).sum()

    precision = float(intersection / sum_s) if sum_s > 0 else 0.0
    recall = float(intersection / sum_v) if sum_v > 0 else 0.0
    f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    iou = float(intersection / union) if union > 0 else 0.0

    return f1, precision, recall, iou


def find_best_offset_fft(
    vad_mask: np.ndarray,
    sub_mask: np.ndarray,
    target_fps: int = 100,
    max_offset_sec: Optional[float] = None
) -> Tuple[float, float]:
    """
    Find optimal time offset using FFT-based zero-mean cross-correlation.
    
    Args:
        vad_mask: 1D speech activity array (1.0 = speech, 0.0 = silence).
        sub_mask: 1D subtitle activity array (1.0 = subtitle, 0.0 = none).
        target_fps: Sampling frequency (default: 100 Hz).
        max_offset_sec: Maximum allowable offset in seconds (+/-). If None, unlimited.
        
    Returns:
        (best_offset_sec, max_correlation_peak)
    """
    n_vad = len(vad_mask)
    n_sub = len(sub_mask)
    if n_vad == 0 or n_sub == 0:
        return 0.0, 0.0

    # Subtract mean for zero-mean cross-correlation (avoids DC bias)
    v_norm = vad_mask - np.mean(vad_mask)
    s_norm = sub_mask - np.mean(sub_mask)

    # Cross-correlation via FFT convolution
    # corr[k] = sum_t v_norm[t] * s_norm[t - lag]
    corr = scipy.signal.fftconvolve(v_norm, s_norm[::-1], mode="full")

    # The zero-lag position in 'full' mode is at index (n_sub - 1)
    zero_idx = n_sub - 1

    if max_offset_sec is not None:
        max_lag_samples = int(round(max_offset_sec * target_fps))
        start_idx = max(0, zero_idx - max_lag_samples)
        end_idx = min(len(corr), zero_idx + max_lag_samples + 1)
    else:
        start_idx = 0
        end_idx = len(corr)

    if start_idx >= end_idx:
        return 0.0, 0.0

    search_region = corr[start_idx:end_idx]
    best_local_idx = int(np.argmax(search_region))
    best_global_idx = start_idx + best_local_idx

    lag_samples = best_global_idx - zero_idx
    best_offset_sec = float(lag_samples) / float(target_fps)
    peak_val = float(search_region[best_local_idx])

    return best_offset_sec, peak_val


def find_best_alignment(
    vad_mask: np.ndarray,
    subs: pysubs2.SSAFile,
    target_fps: int = 100,
    search_framerate_drift: bool = True,
    max_offset_sec: float = 300.0,
    fine_tune_drift: bool = False,
) -> AlignmentResult:
    """
    Find optimal (scale_factor, offset_seconds) aligning subtitle with audio VAD mask.
    
    Args:
        vad_mask: Audio speech activity mask at `target_fps`.
        subs: Parsed subtitle object.
        target_fps: Sampling rate (default 100 Hz).
        search_framerate_drift: Test common standard movie framerate ratios (24/25, 23.976/24, etc.).
        max_offset_sec: Maximum search window in seconds (default +/- 300s = 5 minutes).
        fine_tune_drift: Perform continuous numerical search for arbitrary drift (slightly slower).
        
    Returns:
        AlignmentResult dataclass with optimal parameters and match metrics.
    """
    total_length = len(vad_mask)

    # Initial baseline score (unaligned)
    init_sub_mask = rasterize_subtitles(subs, target_length=total_length, target_fps=target_fps)
    unaligned_f1, _, _, _ = compute_overlap_metrics(vad_mask, init_sub_mask)

    candidates = [1.0]
    if search_framerate_drift:
        candidates = STANDARD_FPS_RATIOS

    best_scale = 1.0
    best_offset = 0.0
    best_f1 = -1.0
    best_metrics = (0.0, 0.0, 0.0, 0.0)

    for scale in candidates:
        # Rasterize subtitle at this candidate scale
        sub_mask = rasterize_subtitles(
            subs,
            target_length=total_length,
            target_fps=target_fps,
            scale=scale,
            offset_sec=0.0
        )
        offset, _ = find_best_offset_fft(
            vad_mask,
            sub_mask,
            target_fps=target_fps,
            max_offset_sec=max_offset_sec
        )

        # Evaluate overlap quality after applying (scale, offset)
        aligned_sub_mask = rasterize_subtitles(
            subs,
            target_length=total_length,
            target_fps=target_fps,
            scale=scale,
            offset_sec=offset
        )
        f1, p, r, iou = compute_overlap_metrics(vad_mask, aligned_sub_mask)

        if f1 > best_f1:
            best_f1 = f1
            best_scale = scale
            best_offset = offset
            best_metrics = (f1, p, r, iou)

    # Optional continuous fine-tuning of scale factor around best candidate
    if fine_tune_drift:
        from scipy.optimize import minimize_scalar

        def objective(s: float) -> float:
            sm = rasterize_subtitles(subs, target_length=total_length, target_fps=target_fps, scale=s)
            off, _ = find_best_offset_fft(vad_mask, sm, target_fps=target_fps, max_offset_sec=max_offset_sec)
            asm = rasterize_subtitles(subs, target_length=total_length, target_fps=target_fps, scale=s, offset_sec=off)
            cur_f1, _, _, _ = compute_overlap_metrics(vad_mask, asm)
            return -cur_f1  # minimize negative F1

        res = minimize_scalar(
            objective,
            bounds=(max(0.90, best_scale - 0.03), min(1.10, best_scale + 0.03)),
            method="bounded",
            options={"xatol": 0.0005, "maxiter": 20}
        )
        fine_scale = float(res.x)
        fine_f1 = -float(res.fun)
        if fine_f1 > best_f1:
            sm = rasterize_subtitles(subs, target_length=total_length, target_fps=target_fps, scale=fine_scale)
            fine_offset, _ = find_best_offset_fft(vad_mask, sm, target_fps=target_fps, max_offset_sec=max_offset_sec)
            asm = rasterize_subtitles(subs, target_length=total_length, target_fps=target_fps, scale=fine_scale, offset_sec=fine_offset)
            best_scale = fine_scale
            best_offset = fine_offset
            best_f1 = fine_f1
            best_metrics = compute_overlap_metrics(vad_mask, asm)

    f1, p, r, iou = best_metrics
    return AlignmentResult(
        offset_seconds=best_offset,
        scale_factor=best_scale,
        overlap_score=best_f1,
        precision=p,
        recall=r,
        iou=iou,
        unaligned_score=unaligned_f1
    )

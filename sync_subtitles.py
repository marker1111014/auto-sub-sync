#!/usr/bin/env python3
"""
Movie Subtitle Auto-Fix Tool (Prototype)
Automatically synchronizes subtitle files (.srt, .ass, .vtt) with movie audio
using Voice Activity Detection (VAD) and FFT Cross-Correlation.
"""

import os
import sys
import io
import argparse
import time
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


from core.audio_extractor import extract_audio_stream, check_ffmpeg
from core.vad_detector import compute_vad_mask
from core.subtitle_io import load_subtitle, save_subtitle, apply_transform
from core.aligner import find_best_alignment


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def run_sync(
    video_path: str,
    subtitle_path: str,
    output_path: str = None,
    search_drift: bool = True,
    fine_tune_drift: bool = False,
    max_offset: float = 300.0,
    vad_aggressiveness: int = 2,
    vad_smooth_ms: int = 300,
    target_fps: int = 100,
) -> str:
    start_total_time = time.time()

    video_p = Path(video_path)
    sub_p = Path(subtitle_path)

    if not video_p.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not sub_p.exists():
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

    if not output_path:
        output_path = str(sub_p.parent / f"{sub_p.stem}_synced{sub_p.suffix}")

    print("=" * 60)
    print("🎬 Movie Subtitle Auto-Fix (VAD + Cross-Correlation)")
    print("=" * 60)
    print(f"📁 Video:    {video_p.name}")
    print(f"📄 Subtitle: {sub_p.name}")
    print(f"💾 Output:   {Path(output_path).name}")
    print("-" * 60)

    # 1. Extract audio
    print(f"[1/4] 🎵 Extracting audio stream via FFmpeg...")
    t0 = time.time()
    pcm_data, sample_rate, duration_sec = extract_audio_stream(
        str(video_p), sample_rate=16000
    )
    t_extract = time.time() - t0
    print(f"      Duration: {format_duration(duration_sec)} | Extracted in {t_extract:.2f}s")

    # 2. VAD Detection
    print(f"[2/4] 🗣️  Running Voice Activity Detection (VAD)...")
    t0 = time.time()
    vad_mask = compute_vad_mask(
        pcm_data,
        sample_rate=sample_rate,
        aggressiveness=vad_aggressiveness,
        smooth_window_ms=vad_smooth_ms,
        target_fps=target_fps,
    )
    t_vad = time.time() - t0
    speech_pct = (vad_mask.sum() / len(vad_mask) * 100) if len(vad_mask) > 0 else 0
    print(f"      Speech ratio: {speech_pct:.1f}% | Processed in {t_vad:.2f}s")

    # 3. Subtitle Parsing & Correlation Matching
    print(f"[3/4] 🔍 Parsing subtitle & computing Cross-Correlation...")
    t0 = time.time()
    subs = load_subtitle(str(sub_p))
    num_events = len([e for e in subs.events if not e.is_comment])
    print(f"      Parsed {num_events} subtitle dialogue cues.")

    result = find_best_alignment(
        vad_mask=vad_mask,
        subs=subs,
        target_fps=target_fps,
        search_framerate_drift=search_drift,
        max_offset_sec=max_offset,
        fine_tune_drift=fine_tune_drift,
    )
    t_align = time.time() - t0
    print(f"      Alignment computed in {t_align:.2f}s")

    # 4. Save synced subtitle
    print(f"[4/4] ✍️  Applying transformation & saving output...")
    synced_subs = apply_transform(
        subs,
        scale=result.scale_factor,
        offset_sec=result.offset_seconds
    )
    save_subtitle(synced_subs, output_path)

    total_time = time.time() - start_total_time

    print("-" * 60)
    print("✨ 同步完成！詳細對齊結果：")
    offset_sign = "+" if result.offset_seconds >= 0 else ""
    print(f"  • 時間平移量 (Offset):   {offset_sign}{result.offset_seconds:.3f} 秒")
    print(f"  • 速度縮放比 (Scale):    {result.scale_factor:.6f}x")
    print(f"  • 原始重疊度 (Score):    {result.unaligned_score * 100:.1f}%")
    print(f"  • 校正後重疊度 (Score):  {result.overlap_score * 100:.1f}% (精確率: {result.precision*100:.1f}%, 召回率: {result.recall*100:.1f}%)")
    print(f"  • 總耗時:                {total_time:.2f} 秒")
    print(f"  • 已儲存至:              {output_path}")
    print("=" * 60)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="自動修復電影字幕時序偏移 (VAD 語音活動檢測 + FFT 互相關)"
    )
    parser.add_argument("video", help="影片或音訊檔案路徑 (例如: movie.mp4 / movie.mkv)")
    parser.add_argument("subtitle", help="字幕檔案路徑 (例如: movie.srt / movie.ass)")
    parser.add_argument(
        "-o", "--output", help="輸出已同步的字幕檔案路徑 (預設為 原檔名_synced.ext)"
    )
    parser.add_argument(
        "--no-drift",
        action="store_true",
        help="關閉幀率漂移檢查 (僅計算固定時間平移，速度更快)",
    )
    parser.add_argument(
        "--fine-tune-drift",
        action="store_true",
        help="啟用連續數值漂移微調 (適合非標準幀率影片)",
    )
    parser.add_argument(
        "--max-offset",
        type=float,
        default=300.0,
        help="允許搜尋的最大時間偏移秒數 (預設: 300 秒 = 5 分鐘)",
    )
    parser.add_argument(
        "--vad-level",
        type=int,
        choices=[0, 1, 2, 3],
        default=2,
        help="VAD 人聲過濾強度 (0 最寬鬆, 3 最嚴格, 預設: 2)",
    )

    args = parser.parse_args()

    try:
        check_ffmpeg()
    except Exception as e:
        print(f"❌ 錯誤: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        run_sync(
            video_path=args.video,
            subtitle_path=args.subtitle,
            output_path=args.output,
            search_drift=not args.no_drift,
            fine_tune_drift=args.fine_tune_drift,
            max_offset=args.max_offset,
            vad_aggressiveness=args.vad_level,
        )
    except Exception as e:
        print(f"❌ 處理失敗: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

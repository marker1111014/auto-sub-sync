#!/usr/bin/env python3
"""
Movie Subtitle Timing Alignment Workbench (Professional NLE / Dark Studio Style)
Strict 0px border-radius, matte dark charcoal palette, zero emojis, high information density.
"""

import os
import sys
import traceback
import ctypes
import subprocess
from pathlib import Path

# Crash handler for GUI
def show_fatal_error(msg: str):
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_crash.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(msg)
    try:
        ctypes.windll.user32.MessageBoxW(0, f"[FATAL ERROR]\n\n{msg}", "SUBTITLE WORKBENCH ERROR", 0x10)
    except Exception:
        pass

sys.excepthook = lambda t, v, tb: show_fatal_error("".join(traceback.format_exception(t, v, tb)))

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QCheckBox,
    QProgressBar, QFrame, QMessageBox, QGroupBox, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont

from core.audio_extractor import extract_audio_stream, check_ffmpeg
from core.vad_detector import compute_vad_mask
from core.subtitle_io import load_subtitle, save_subtitle, apply_transform
from core.aligner import find_best_alignment

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".webm", ".m4v"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt"}


class SyncWorker(QThread):
    progress_signal = pyqtSignal(int, str)  # (percent, status_text)
    finished_signal = pyqtSignal(bool, dict, str)  # (success, result_data, error_msg)

    def __init__(self, video_path: str, sub_path: str, out_path: str,
                 search_drift: bool, fine_tune_drift: bool, max_offset: float):
        super().__init__()
        self.video_path = video_path
        self.sub_path = sub_path
        self.out_path = out_path
        self.search_drift = search_drift
        self.fine_tune_drift = fine_tune_drift
        self.max_offset = max_offset

    def run(self):
        try:
            # 1. Audio Extraction
            self.progress_signal.emit(10, "[階段 1/4] 抽取影片人聲音訊 (FFmpeg 16kHz PCM)...")
            pcm, sr, duration_sec = extract_audio_stream(self.video_path, sample_rate=16000)

            # 2. VAD Detection
            self.progress_signal.emit(40, "[階段 2/4] 執行語音活動檢測 (WebRTC VAD)...")
            vad_mask = compute_vad_mask(pcm, sample_rate=sr, target_fps=100)

            # 3. Subtitle Alignment
            self.progress_signal.emit(70, "[階段 3/4] 解析字幕時序並執行 FFT 互相關運算...")
            subs = load_subtitle(self.sub_path)
            res = find_best_alignment(
                vad_mask=vad_mask,
                subs=subs,
                target_fps=100,
                search_framerate_drift=self.search_drift,
                max_offset_sec=self.max_offset,
                fine_tune_drift=self.fine_tune_drift,
            )

            # 4. Save synced subtitle
            self.progress_signal.emit(90, "[階段 4/4] 寫入校正後字幕檔 (UTF-8)...")
            synced = apply_transform(subs, scale=res.factor if hasattr(res, 'factor') else res.scale_factor, offset_sec=res.offset_seconds)
            save_subtitle(synced, self.out_path)

            self.progress_signal.emit(100, "[完成] 時序同步校正已完成。")
            result_data = {
                "offset": res.offset_seconds,
                "scale": res.scale_factor,
                "score_before": res.unaligned_score * 100,
                "score_after": res.overlap_score * 100,
                "precision": res.precision * 100,
                "recall": res.recall * 100,
                "output_path": self.out_path,
                "duration": duration_sec,
            }
            self.finished_signal.emit(True, result_data, "")
        except Exception as e:
            self.finished_signal.emit(False, {}, str(e))


class DropArea(QFrame):
    """Area that accepts drag and drop of video/subtitle files."""
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        file_paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if file_paths:
            self.files_dropped.emit(file_paths)
            event.acceptProposedAction()


class SubtitleSyncApp(QMainWindow):
    def __init__(self, initial_video=None, initial_sub=None):
        super().__init__()
        self.worker = None
        self.last_output_path = None
        self.init_ui()

        if initial_video:
            self.set_video(initial_video)
        if initial_sub:
            self.set_subtitle(initial_sub)

    def init_ui(self):
        self.setWindowTitle("SUBTITLE ALIGNMENT WORKBENCH v1.0.0 [NLE STUDIO]")
        self.resize(720, 680)
        self.setMinimumSize(640, 600)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(18, 18, 18, 18)

        # 1. Header Toolbar Bar (Studio Header)
        header_frame = QFrame()
        header_frame.setObjectName("headerFrame")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_label = QLabel("SUBTITLE TIMING WORKBENCH")
        title_label.setObjectName("titleLabel")
        desc_label = QLabel("電影字幕時序自動校正工作站 ｜ VAD 聲學活動特徵 ＆ FFT 互相關比對引擎")
        desc_label.setObjectName("subTitleLabel")
        title_col.addWidget(title_label)
        title_col.addWidget(desc_label)

        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.engine_badge = QLabel("[ENGINE: READY]")
        self.engine_badge.setObjectName("badgeReady")
        header_layout.addWidget(self.engine_badge)

        main_layout.addWidget(header_frame)

        # 2. Drag & Drop Zone
        self.drop_area = DropArea()
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.setContentsMargins(14, 16, 14, 16)
        drop_layout.setSpacing(6)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_tag = QLabel("[ 檔案拖曳導入區 / DRAG & DROP ZONE ]")
        drop_tag.setObjectName("dropTag")
        drop_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_hint = QLabel("支援直接拖入影片檔 (.mp4 / .mkv / .avi / .ts) 或字幕檔 (.srt / .ass / .vtt)")
        drop_hint.setObjectName("dropHint")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_layout.addWidget(drop_tag)
        drop_layout.addWidget(drop_hint)
        self.drop_area.files_dropped.connect(self.handle_dropped_files)
        main_layout.addWidget(self.drop_area)

        # 3. File Input Matrix Group
        form_group = QGroupBox("檔案來源與路徑配置 (SOURCE CONFIGURATION)")
        form_layout = QGridLayout(form_group)
        form_layout.setContentsMargins(14, 16, 14, 14)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(10)

        # Video Row
        v_tag = QLabel("影片來源 (Video):")
        v_tag.setObjectName("fieldLabel")
        self.v_input = QLineEdit()
        self.v_input.setPlaceholderText("選取或拖入本地電影/影集檔案路徑...")
        self.v_btn = QPushButton("瀏覽...")
        self.v_btn.clicked.connect(self.browse_video)
        form_layout.addWidget(v_tag, 0, 0)
        form_layout.addWidget(self.v_input, 0, 1)
        form_layout.addWidget(self.v_btn, 0, 2)

        # Subtitle Row
        s_tag = QLabel("待修字幕 (Sub):")
        s_tag.setObjectName("fieldLabel")
        self.s_input = QLineEdit()
        self.s_input.setPlaceholderText("選取或拖入待校正字幕檔 (.srt, .ass, .vtt)...")
        self.s_btn = QPushButton("瀏覽...")
        self.s_btn.clicked.connect(self.browse_subtitle)
        form_layout.addWidget(s_tag, 1, 0)
        form_layout.addWidget(self.s_input, 1, 1)
        form_layout.addWidget(self.s_btn, 1, 2)

        # Output Row
        o_tag = QLabel("輸出目標 (Dest):")
        o_tag.setObjectName("fieldLabel")
        self.o_input = QLineEdit()
        self.o_input.setPlaceholderText("預設輸出至原字幕所在目錄: [原檔名]_synced.srt")
        self.o_btn = QPushButton("自訂...")
        self.o_btn.clicked.connect(self.browse_output)
        form_layout.addWidget(o_tag, 2, 0)
        form_layout.addWidget(self.o_input, 2, 1)
        form_layout.addWidget(self.o_btn, 2, 2)

        main_layout.addWidget(form_group)

        # 4. Engine Options
        opt_group = QGroupBox("校正演算法參數 (ENGINE SETTINGS)")
        opt_layout = QHBoxLayout(opt_group)
        opt_layout.setContentsMargins(14, 12, 14, 12)
        opt_layout.setSpacing(20)

        self.drift_check = QCheckBox("啟用標準電影幀率漂移比對 (23.976 / 24 / 25 fps PAL 自動辨識)")
        self.drift_check.setChecked(True)
        opt_layout.addWidget(self.drift_check)

        opt_layout.addStretch()
        param_label = QLabel("搜尋範圍: ±300s  |  採樣頻率: 100Hz (10ms)")
        param_label.setObjectName("paramLabel")
        opt_layout.addWidget(param_label)

        main_layout.addWidget(opt_group)

        # 5. Primary Action Button
        self.start_btn = QPushButton("[ 執行時序自動同步與校正 ]")
        self.start_btn.setObjectName("BtnPrimary")
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self.start_sync)
        main_layout.addWidget(self.start_btn)

        # 6. Progress & Status Console Bar
        progress_box = QVBoxLayout()
        progress_box.setSpacing(6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        progress_box.addWidget(self.progress_bar)

        self.status_label = QLabel("[狀態: 就緒] 請配置影片與字幕來源後開始執行。")
        self.status_label.setObjectName("statusLabel")
        progress_box.addWidget(self.status_label)

        main_layout.addLayout(progress_box)

        # 7. Result Dashboard (Hidden initially)
        self.result_box = QFrame()
        self.result_box.setObjectName("resultBox")
        self.result_layout = QVBoxLayout(self.result_box)
        self.result_layout.setContentsMargins(14, 12, 14, 12)
        self.result_layout.setSpacing(10)

        self.result_text = QLabel()
        self.result_text.setTextFormat(Qt.TextFormat.RichText)
        self.result_layout.addWidget(self.result_text)

        btn_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("[ 開啟輸出目錄並標記檔案 ]")
        self.open_folder_btn.setObjectName("btnOpenFolder")
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        btn_row.addWidget(self.open_folder_btn)
        btn_row.addStretch()

        self.result_layout.addLayout(btn_row)
        self.result_box.setVisible(False)
        main_layout.addWidget(self.result_box)

        main_layout.addStretch()

    def handle_dropped_files(self, paths):
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext in VIDEO_EXTS:
                self.set_video(path)
            elif ext in SUB_EXTS:
                self.set_subtitle(path)

    def set_video(self, path):
        self.v_input.setText(path)
        # Auto-detect matching subtitle in same directory if subtitle not yet selected
        if not self.s_input.text():
            p = Path(path)
            parent = p.parent
            stem = p.stem.lower()
            candidates = []
            for file in parent.iterdir():
                if file.is_file() and file.suffix.lower() in SUB_EXTS:
                    candidates.append(file)
            matched = None
            for c in candidates:
                if stem in c.stem.lower() or c.stem.lower() in stem:
                    matched = str(c)
                    break
            if not matched and candidates:
                matched = str(candidates[0])
            if matched:
                self.set_subtitle(matched)

    def set_subtitle(self, path):
        self.s_input.setText(path)
        if not self.o_input.text():
            p = Path(path)
            default_out = p.parent / f"{p.stem}_synced{p.suffix}"
            self.o_input.setText(str(default_out))

    def browse_video(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "選取電影影片檔案", "",
            "影片檔案 (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.ts *.webm *.m4v);;所有檔案 (*.*)"
        )
        if file:
            self.set_video(file)

    def browse_subtitle(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "選取字幕檔案", "",
            "字幕檔案 (*.srt *.ass *.ssa *.vtt);;所有檔案 (*.*)"
        )
        if file:
            self.set_subtitle(file)

    def browse_output(self):
        file, _ = QFileDialog.getSaveFileName(
            self, "選擇儲存輸出路徑", self.o_input.text() or "",
            "SRT 字幕 (*.srt);;ASS 字幕 (*.ass);;所有檔案 (*.*)"
        )
        if file:
            self.o_input.setText(file)

    def start_sync(self):
        v_path = self.v_input.text().strip()
        s_path = self.s_input.text().strip()
        o_path = self.o_input.text().strip()

        if not v_path or not os.path.isfile(v_path):
            QMessageBox.warning(self, "[輸入驗證警告]", "請先指定有效的影片來源檔案。")
            return
        if not s_path or not os.path.isfile(s_path):
            QMessageBox.warning(self, "[輸入驗證警告]", "請先指定有效的待修復字幕檔案。")
            return

        if not o_path:
            p = Path(s_path)
            o_path = str(p.parent / f"{p.stem}_synced{p.suffix}")
            self.o_input.setText(o_path)

        try:
            check_ffmpeg()
        except Exception as e:
            QMessageBox.critical(self, "[系統環境錯誤]", str(e))
            return

        self.start_btn.setEnabled(False)
        self.result_box.setVisible(False)
        self.progress_bar.setValue(5)
        self.status_label.setText("[狀態: 處理中] 初始化音訊與演算法環境...")
        self.engine_badge.setText("[ENGINE: BUSY]")
        self.engine_badge.setObjectName("badgeBusy")
        self.engine_badge.setStyleSheet("background-color: #2a2418; color: #fbbf24; border: 1px solid #5a4820;")

        self.worker = SyncWorker(
            video_path=v_path,
            sub_path=s_path,
            out_path=o_path,
            search_drift=self.drift_check.isChecked(),
            fine_tune_drift=False,
            max_offset=300.0,
        )
        self.worker.progress_signal.connect(self.on_progress)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, percent, text):
        self.progress_bar.setValue(percent)
        self.status_label.setText(f"[狀態: 處理中] {text}")

    def on_finished(self, success, data, error_msg):
        self.start_btn.setEnabled(True)
        if success:
            self.engine_badge.setText("[ENGINE: PASS]")
            self.engine_badge.setStyleSheet("background-color: #1c261e; color: #4ade80; border: 1px solid #2a402d;")
            self.last_output_path = data["output_path"]
            offset = data["offset"]
            sign = "+" if offset >= 0 else ""
            res_html = f"""
            <div style="font-family: 'Segoe UI', monospace; line-height: 1.6;">
              <span style="color: #4ade80; font-weight: bold; font-size: 13px;">[校正分析報告 - 成功完成]</span>
              <table style="width: 100%; border-collapse: collapse; margin-top: 8px;">
                <tr>
                  <td style="color: #888888; width: 140px; padding: 2px 0;">時間軸平移量 (Offset):</td>
                  <td style="color: #ffffff; font-weight: bold;">{sign}{offset:.3f} 秒</td>
                </tr>
                <tr>
                  <td style="color: #888888; padding: 2px 0;">影音速度縮放 (Scale):</td>
                  <td style="color: #ffffff; font-weight: bold;">{data['scale']:.6f}x</td>
                </tr>
                <tr>
                  <td style="color: #888888; padding: 2px 0;">語音特徵重疊匹配度:</td>
                  <td style="color: #ffffff; font-weight: bold;">
                    {data['score_before']:.1f}% ──▶ <span style="color: #4ade80;">{data['score_after']:.1f}%</span> 
                    <span style="color: #888888; font-weight: normal; font-size: 11px;">(精確率: {data['precision']:.1f}%, 召回率: {data['recall']:.1f}%)</span>
                  </td>
                </tr>
                <tr>
                  <td style="color: #888888; padding: 2px 0;">已儲存檔案:</td>
                  <td style="color: #79c0ff; font-weight: bold;">{os.path.basename(data['output_path'])}</td>
                </tr>
              </table>
            </div>
            """
            self.result_text.setText(res_html)
            self.result_box.setVisible(True)
            self.status_label.setText("[狀態: 完成] 字幕時序校正已成功套用並儲存。")
        else:
            self.engine_badge.setText("[ENGINE: FAIL]")
            self.engine_badge.setStyleSheet("background-color: #2a1d1d; color: #e07a7a; border: 1px solid #5a2e2e;")
            self.progress_bar.setValue(0)
            self.status_label.setText(f"[狀態: 失敗] {error_msg}")
            QMessageBox.critical(self, "[任務執行失敗]", f"處理過程中發生不可預期之錯誤：\n\n{error_msg}")

    def open_output_folder(self):
        if self.last_output_path and os.path.isfile(self.last_output_path):
            norm_path = os.path.normpath(self.last_output_path)
            subprocess.run(["explorer", f"/select,{norm_path}"])


WORKBENCH_QSS = """
/* =========================================================================
   PROFESSIONAL NLE / DARK STUDIO WORKBENCH STYLESHEET (0px Border-Radius)
   ========================================================================= */

/* Global Window Background */
QMainWindow {
    background-color: #181818;
}

QWidget {
    font-family: "Segoe UI", "Microsoft JhengHei UI", sans-serif;
    color: #d4d4d4;
    font-size: 12px;
}

/* Header Frame */
#headerFrame {
    background-color: #212121;
    border: 1px solid #303030;
    border-radius: 0px;
}

#titleLabel {
    font-size: 14px;
    font-weight: bold;
    color: #ffffff;
    letter-spacing: 1px;
}

#subTitleLabel {
    font-size: 11px;
    color: #888888;
}

/* Engine Badges (Monospace Rectangles) */
#badgeReady {
    background-color: #1c261e;
    color: #4ade80;
    border: 1px solid #2a402d;
    border-radius: 0px;
    padding: 3px 8px;
    font-family: monospace;
    font-weight: bold;
    font-size: 11px;
}

#badgeBusy {
    background-color: #2a2418;
    color: #fbbf24;
    border: 1px solid #5a4820;
    border-radius: 0px;
    padding: 3px 8px;
    font-family: monospace;
    font-weight: bold;
    font-size: 11px;
}

#badgeFail {
    background-color: #2a1d1d;
    color: #e07a7a;
    border: 1px solid #5a2e2e;
    border-radius: 0px;
    padding: 3px 8px;
    font-family: monospace;
    font-weight: bold;
    font-size: 11px;
}

/* Drag & Drop Zone */
#dropArea {
    border: 1px dashed #3a3a3a;
    border-radius: 0px;
    background-color: #1c1c1c;
}

#dropArea:hover {
    background-color: #202630;
    border-color: #0e639c;
}

#dropTag {
    color: #0e639c;
    font-weight: bold;
    font-size: 12px;
    letter-spacing: 1px;
}

#dropHint {
    color: #777777;
    font-size: 11px;
}

/* Group Boxes (Panels) */
QGroupBox {
    background-color: #212121;
    border: 1px solid #303030;
    border-radius: 0px;
    margin-top: 18px;
    padding-top: 12px;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    top: 2px;
    padding: 0 4px;
    color: #909090;
    font-size: 11px;
    text-transform: uppercase;
}

/* Input Fields */
QLineEdit {
    background-color: #1a1a1a;
    border: 1px solid #383838;
    border-radius: 0px;
    color: #d4d4d4;
    padding: 6px 8px;
    font-size: 12px;
    selection-background-color: #0e639c;
}

QLineEdit:focus {
    border: 1px solid #0e639c;
    background-color: #161616;
}

#fieldLabel {
    color: #aaaaaa;
    font-weight: 500;
}

#paramLabel {
    color: #777777;
    font-size: 11px;
    font-family: monospace;
}

/* Standard Buttons */
QPushButton {
    background-color: #2b2b2b;
    color: #d4d4d4;
    border: 1px solid #3a3a3a;
    border-radius: 0px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #363636;
    border-color: #4a4a4a;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #1f1f1f;
    border-color: #2b2b2b;
}

QPushButton:disabled {
    background-color: #1c1c1c;
    color: #555555;
    border-color: #2b2b2b;
}

/* Primary Action Execution Button (Studio Cobalt Blue) */
QPushButton#BtnPrimary {
    background-color: #0e639c;
    color: #ffffff;
    border: 1px solid #1177bb;
    border-radius: 0px;
    font-weight: bold;
    font-size: 13px;
    letter-spacing: 0.5px;
}

QPushButton#BtnPrimary:hover {
    background-color: #1177bb;
    border-color: #2b88cc;
}

QPushButton#BtnPrimary:pressed {
    background-color: #094770;
}

QPushButton#BtnPrimary:disabled {
    background-color: #1c2633;
    color: #556677;
    border-color: #223344;
}

/* Open Folder Button */
QPushButton#btnOpenFolder {
    background-color: #1c261e;
    color: #4ade80;
    border: 1px solid #2a402d;
    border-radius: 0px;
    padding: 6px 14px;
    font-weight: bold;
}

QPushButton#btnOpenFolder:hover {
    background-color: #243327;
    border-color: #38573d;
}

/* Flat Rectangular Progress Bar */
QProgressBar {
    background-color: #1c1c1c;
    border: 1px solid #303030;
    border-radius: 0px;
    color: #d4d4d4;
    font-size: 10px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #0e639c;
    border-radius: 0px;
}

#statusLabel {
    color: #888888;
    font-size: 11px;
    font-family: monospace;
}

/* Result Dashboard Box */
#resultBox {
    background-color: #1a1e1b;
    border: 1px solid #2a402d;
    border-radius: 0px;
}

/* Checkbox (Flat Square Indicator) */
QCheckBox {
    color: #cccccc;
    spacing: 8px;
    font-size: 12px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #4a4a4a;
    background: #1c1c1c;
    border-radius: 0px;
}

QCheckBox::indicator:hover {
    border-color: #0e639c;
}

QCheckBox::indicator:checked {
    background: #0e639c;
    border-color: #1177bb;
}

/* Message Box Dialogs */
QMessageBox {
    background-color: #212121;
    border: 1px solid #383838;
}

QMessageBox QLabel {
    color: #d4d4d4;
}

QMessageBox QPushButton {
    min-width: 70px;
}
"""


def main():
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        app.setStyleSheet(WORKBENCH_QSS)

        # Base font
        font = QFont("Segoe UI", 9)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        app.setFont(font)

        # Check CLI arguments if user dragged files onto batch/vbs script
        v_arg = None
        s_arg = None
        if len(sys.argv) > 1:
            for arg in sys.argv[1:]:
                ext = Path(arg).suffix.lower()
                if ext in VIDEO_EXTS and not v_arg:
                    v_arg = arg
                elif ext in SUB_EXTS and not s_arg:
                    s_arg = arg

        window = SubtitleSyncApp(initial_video=v_arg, initial_sub=s_arg)
        window.show()
        ret = app.exec()
        sys.exit(ret)
    except Exception:
        show_fatal_error(traceback.format_exc())


if __name__ == "__main__":
    main()

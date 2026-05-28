from datetime import datetime
import json
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, List

from PyQt5.QtCore import QThread, pyqtSignal

from app.common.config import cfg
from app.config import WORK_PATH, CACHE_PATH
from app.core.highlight_reel import render_highlight_reel
from app.core.shorts import ShortCandidate, ShortsProcessor
from app.thread.auto_shorts_thread import AutoShortsTranscribeThread


class HighlightReelAnalyzeThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        video_path: str,
        target_reel_minutes: int,
        interest_level: str,
        interest_threshold_percent: int,
        boring_profile: str,
        asr_backend: str = "gpu",
        use_asr_cache: bool = True,
        use_candidates_cache: bool = True,
    ):
        super().__init__()
        self.video_path = video_path
        self.target_reel_minutes = max(5, int(target_reel_minutes or 30))
        self.interest_level = str(interest_level or "balanced").strip().lower()
        self.interest_threshold_percent = int(interest_threshold_percent)
        self.boring_profile = str(boring_profile or "balanced").strip().lower()
        self.asr_backend = str(asr_backend or "gpu").strip().lower()
        self.use_asr_cache = bool(use_asr_cache)
        self.use_candidates_cache = bool(use_candidates_cache)

    @staticmethod
    def _cache_dir() -> Path:
        p = CACHE_PATH / "highlight_reel"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _build_candidates_cache_key(self, asr_json: Dict) -> str:
        raw = json.dumps(
            {
                "v": 1,
                "asr": asr_json,
                "target_reel_minutes": self.target_reel_minutes,
                "interest_level": self.interest_level,
                "interest_threshold_percent": self.interest_threshold_percent,
                "boring_profile": self.boring_profile,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _smooth_stream_candidates(self, candidates: List[ShortCandidate]) -> List[ShortCandidate]:
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda c: int(c.start_ms))
        merged: List[ShortCandidate] = []
        max_merge_gap_ms = 3500  # для стрим-нарезки склеиваем близкие пики
        max_merged_len_ms = 180_000

        cur = ordered[0]
        for nxt in ordered[1:]:
            gap = int(nxt.start_ms) - int(cur.end_ms)
            merged_len_if_join = int(nxt.end_ms) - int(cur.start_ms)
            if gap <= max_merge_gap_ms and merged_len_if_join <= max_merged_len_ms:
                cur.end_ms = max(int(cur.end_ms), int(nxt.end_ms))
                cur.score = max(float(cur.score), float(nxt.score))
                if hasattr(cur, "quality_score") and hasattr(nxt, "quality_score"):
                    cur.quality_score = max(float(getattr(cur, "quality_score", 0.0)), float(getattr(nxt, "quality_score", 0.0)))
                if not (cur.title or "").strip() and (nxt.title or "").strip():
                    cur.title = nxt.title
                continue
            merged.append(cur)
            cur = nxt
        merged.append(cur)
        return merged

    def run(self):
        try:
            self.progress.emit(5, "ASR анализ видео...")
            transcribe_thread = AutoShortsTranscribeThread(self.video_path)
            prev_fw_device = str(cfg.get(cfg.faster_whisper_device) or "cuda")
            try:
                cfg.set(cfg.faster_whisper_device, "cuda" if self.asr_backend == "gpu" else "cpu")
            except Exception:
                pass
            payload_box: Dict = {}
            err_box: Dict = {}

            if not self.use_asr_cache:
                transcribe_thread._load_asr_cache = lambda _k: None
                transcribe_thread._save_asr_cache = lambda _k, _a: None

            transcribe_thread.finished.connect(lambda payload: payload_box.update({"payload": payload}))
            transcribe_thread.error.connect(lambda err: err_box.update({"err": err}))
            transcribe_thread.progress.connect(lambda p, m: self.progress.emit(min(45, max(5, p // 2)), m))
            transcribe_thread.run()
            try:
                cfg.set(cfg.faster_whisper_device, prev_fw_device)
            except Exception:
                pass

            if err_box.get("err"):
                raise RuntimeError(str(err_box["err"]))

            payload = payload_box.get("payload") or {}
            asr_json = payload.get("asr_json")
            if not asr_json:
                raise RuntimeError("Не удалось получить ASR данные")

            candidates_cache_key = self._build_candidates_cache_key(asr_json)
            candidates_cache_file = self._cache_dir() / f"candidates_{candidates_cache_key}.json"
            if self.use_candidates_cache and candidates_cache_file.exists():
                try:
                    cached = json.loads(candidates_cache_file.read_text(encoding="utf-8"))
                    if isinstance(cached, list):
                        self.progress.emit(100, f"Кандидаты загружены из кэша: {len(cached)}")
                        self.finished.emit(cached)
                        return
                except Exception:
                    pass

            llm_cfg = AutoShortsTranscribeThread._resolve_llm_config()
            profile = self.interest_level
            if profile == "high":
                min_duration_s, max_duration_s = 20, 90
                min_candidates, max_candidates = 25, 120
                effective_threshold = max(60, self.interest_threshold_percent)
            elif profile == "low":
                min_duration_s, max_duration_s = 35, 180
                min_candidates, max_candidates = 12, 70
                effective_threshold = min(50, self.interest_threshold_percent)
            else:
                min_duration_s, max_duration_s = 25, 140
                min_candidates, max_candidates = 18, 90
                effective_threshold = self.interest_threshold_percent

            processor = ShortsProcessor(
                min_duration_s=min_duration_s,
                max_duration_s=max_duration_s,
                llm_base_url=llm_cfg["base_url"],
                llm_api_key=llm_cfg["api_key"],
                llm_model=llm_cfg["model"],
                min_candidates=min_candidates,
                max_candidates=max_candidates,
                auto_filter_weak_candidates=True,
                auto_filter_profile=self.boring_profile,
                interest_threshold_percent=effective_threshold,
                llm_search_intensity=4,
            )

            self.progress.emit(50, "Поиск интересных моментов...")
            from app.core.bk_asr.asr_data import ASRData

            candidates = processor.find_candidates(
                ASRData.from_json(asr_json),
                progress_cb=lambda p, m: self.progress.emit(min(95, 50 + int(p * 0.45)), m),
            )
            candidates = self._smooth_stream_candidates(candidates)

            # Подбор до целевой длительности нарезки
            target_ms = int(self.target_reel_minutes * 60_000)
            selected: List[ShortCandidate] = []
            acc = 0
            for c in sorted(candidates, key=lambda x: float(getattr(x, "quality_score", x.score) or x.score), reverse=True):
                dur = max(0, int(c.end_ms) - int(c.start_ms))
                if dur <= 0:
                    continue
                if acc < target_ms or len(selected) < 4:
                    selected.append(c)
                    acc += dur
                if acc >= int(target_ms * 1.12):
                    break
            candidates = sorted(selected or candidates[:20], key=lambda x: int(x.start_ms))

            self.progress.emit(100, f"Анализ завершён. Моментов: {len(candidates)}")
            result = [c.to_dict() for c in candidates]
            if self.use_candidates_cache:
                try:
                    candidates_cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class HighlightReelRenderThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        video_path: str,
        selected_candidates: List[Dict],
        output_name: str,
        head_pad_ms: int,
        tail_pad_ms: int,
        export_vertical: bool = False,
        render_backend: str = "gpu",
    ):
        super().__init__()
        self.video_path = video_path
        self.selected_candidates = selected_candidates
        self.output_name = output_name
        self.head_pad_ms = int(head_pad_ms)
        self.tail_pad_ms = int(tail_pad_ms)
        self.export_vertical = bool(export_vertical)
        self.render_backend = str(render_backend or "gpu").strip().lower()

    def run(self):
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = WORK_PATH / "highlight_reels" / stamp
            out_dir.mkdir(parents=True, exist_ok=True)

            candidates = [
                ShortCandidate(
                    start_ms=int(c["start_ms"]),
                    end_ms=int(c["end_ms"]),
                    score=float(c.get("score", 0.0) or 0.0),
                    title=str(c.get("title", "") or ""),
                    reason=str(c.get("reason", "") or ""),
                    excerpt=str(c.get("excerpt", "") or ""),
                    viral_title=str(c.get("viral_title", "") or ""),
                    speech_ranges=c.get("speech_ranges") or [],
                )
                for c in self.selected_candidates
            ]
            path = render_highlight_reel(
                input_video=self.video_path,
                candidates=candidates,
                output_dir=str(out_dir),
                output_name=self.output_name,
                head_pad_ms=self.head_pad_ms,
                tail_pad_ms=self.tail_pad_ms,
                render_backend=self.render_backend,
                progress_cb=lambda p, m: self.progress.emit(p, m),
            )
            outputs = {"main": path}
            if self.export_vertical:
                self.progress.emit(92, "Экспорт вертикальной версии 9:16...")
                vertical_path = str(Path(path).with_name(Path(path).stem + "_9x16.mp4"))
                vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
                use_gpu = self.render_backend in {"gpu", "cuda"}
                cmd = [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    path,
                    "-vf",
                    vf,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-y",
                    vertical_path,
                ]
                if use_gpu:
                    cmd[cmd.index("-c:a"):cmd.index("-c:a")] = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23", "-b:v", "0"]
                else:
                    cmd[cmd.index("-c:a"):cmd.index("-c:a")] = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=(subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
                )
                if proc.returncode == 0 and Path(vertical_path).exists():
                    outputs["vertical_9x16"] = vertical_path

            report = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_video": self.video_path,
                "selected_count": len(candidates),
                "head_pad_ms": self.head_pad_ms,
                "tail_pad_ms": self.tail_pad_ms,
                "avg_score": round(
                    sum(float(getattr(c, "quality_score", c.score) or c.score) for c in candidates) / max(1, len(candidates)),
                    3,
                ),
                "outputs": outputs,
                "segments": [
                    {
                        "start_ms": int(c.start_ms),
                        "end_ms": int(c.end_ms),
                        "duration_ms": int(max(0, c.end_ms - c.start_ms)),
                        "title": str(c.title or ""),
                        "score": float(c.score),
                        "quality_score": float(getattr(c, "quality_score", c.score) or c.score),
                    }
                    for c in candidates
                ],
            }
            report_path = Path(path).with_suffix(".report.json")
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))


class HighlightReelPreviewThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, video_path: str, candidate: Dict, head_pad_ms: int, tail_pad_ms: int):
        super().__init__()
        self.video_path = video_path
        self.candidate = dict(candidate or {})
        self.head_pad_ms = int(head_pad_ms)
        self.tail_pad_ms = int(tail_pad_ms)

    def run(self):
        try:
            out_dir = WORK_PATH / "highlight_reels" / "preview"
            out_dir.mkdir(parents=True, exist_ok=True)
            c = self.candidate
            candidate = ShortCandidate(
                start_ms=int(c.get("start_ms", 0)),
                end_ms=int(c.get("end_ms", 0)),
                score=float(c.get("score", 0.0) or 0.0),
                title=str(c.get("title", "") or "preview"),
                reason=str(c.get("reason", "") or "preview"),
                excerpt=str(c.get("excerpt", "") or "preview"),
                viral_title=str(c.get("viral_title", "") or "preview"),
                speech_ranges=c.get("speech_ranges") or [],
            )
            path = render_highlight_reel(
                input_video=self.video_path,
                candidates=[candidate],
                output_dir=str(out_dir),
                output_name="preview_reel.mp4",
                head_pad_ms=self.head_pad_ms,
                tail_pad_ms=self.tail_pad_ms,
            )
            self.finished.emit(path)
        except Exception as e:
            self.error.emit(str(e))

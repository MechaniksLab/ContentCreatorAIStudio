import subprocess
import tempfile
from pathlib import Path
from typing import List

from app.core.shorts.shorts_processor import ShortCandidate
from app.core.utils.media_binaries import resolve_project_media_binary


FFMPEG_BIN = resolve_project_media_binary("ffmpeg")


def _run_ffmpeg(cmd: list[str]):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
    )


def _cut_segment(input_video: str, output_video: str, start_s: float, end_s: float, render_backend: str = "cpu"):
    backend = (render_backend or "cpu").strip().lower()
    use_gpu = backend in {"gpu", "cuda"}
    cmd = [
        FFMPEG_BIN,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_s:.3f}",
        "-to",
        f"{end_s:.3f}",
        "-i",
        input_video,
    ]
    if use_gpu:
        cmd += [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-cq",
            "23",
            "-b:v",
            "0",
        ]
    else:
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
        ]
    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-y",
        output_video,
    ]
    proc = _run_ffmpeg(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"Ошибка нарезки сегмента: {proc.stderr[-500:]}")


def render_highlight_reel(
    input_video: str,
    candidates: List[ShortCandidate],
    output_dir: str,
    output_name: str = "highlight_reel.mp4",
    head_pad_ms: int = 200,
    tail_pad_ms: int = 250,
    render_backend: str = "cpu",
    progress_cb=None,
) -> str:
    if not candidates:
        raise RuntimeError("Нет кандидатов для сборки нарезки")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / output_name

    with tempfile.TemporaryDirectory(prefix="reel_segments_") as td:
        td_path = Path(td)
        segment_files: List[Path] = []

        total = len(candidates)
        for i, c in enumerate(candidates, 1):
            start_s = max(0.0, (int(c.start_ms) - int(head_pad_ms)) / 1000.0)
            end_s = max(start_s + 0.2, (int(c.end_ms) + int(tail_pad_ms)) / 1000.0)
            seg_path = td_path / f"seg_{i:04d}.mp4"
            _cut_segment(input_video, str(seg_path), start_s, end_s, render_backend=render_backend)
            segment_files.append(seg_path)
            if progress_cb:
                progress_cb(int((i / max(1, total)) * 55), f"Подготовка сегментов: {i}/{total}")

        concat_txt = td_path / "concat.txt"
        concat_txt.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in segment_files),
            encoding="utf-8",
        )

        concat_cmd = [
            FFMPEG_BIN,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c",
            "copy",
            "-y",
            str(output_path),
        ]
        proc = _run_ffmpeg(concat_cmd)
        if proc.returncode != 0:
            # fallback: re-encode concat
            backend = (render_backend or "cpu").strip().lower()
            use_gpu = backend in {"gpu", "cuda"}
            concat_cmd = [
                FFMPEG_BIN,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
            ]
            if use_gpu:
                concat_cmd += [
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "p5",
                    "-cq",
                    "23",
                    "-b:v",
                    "0",
                ]
            else:
                concat_cmd += [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "22",
                ]
            concat_cmd += ["-c:a", "aac", "-b:a", "160k", "-y", str(output_path)]
            proc = _run_ffmpeg(concat_cmd)
            if proc.returncode != 0:
                raise RuntimeError(f"Ошибка сборки нарезки: {proc.stderr[-500:]}")

    if progress_cb:
        progress_cb(100, "Нарезка собрана")
    return str(output_path)

#!/usr/bin/env python3
"""Render a five-image / five-voiceover vertical social video with FFmpeg."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode:
        detail = result.stderr or result.stdout or "Unknown command failure"
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result.stdout or ""


def load_json(source: str) -> dict[str, Any]:
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=60) as response:
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def download(source: str, destination: Path) -> Path:
    if source.startswith(("https://", "http://")):
        request = urllib.request.Request(source, headers={"User-Agent": "TheBuiltSocialRenderer/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    else:
        local = Path(source).expanduser().resolve()
        if not local.is_file():
            raise ValueError(f"Asset does not exist: {source}")
        shutil.copy2(local, destination)
    if destination.stat().st_size == 0:
        raise ValueError(f"Downloaded asset is empty: {source}")
    return destination


def probe(path: Path) -> dict[str, Any]:
    raw = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=index,codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    return json.loads(raw)


def duration_seconds(info: dict[str, Any]) -> float:
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Asset has no measurable duration") from exc


def has_stream(info: dict[str, Any], stream_type: str) -> bool:
    return any(stream.get("codec_type") == stream_type for stream in info.get("streams", []))


def safe_colour(value: str, fallback: str) -> str:
    candidate = str(value or fallback).strip().lstrip("#")
    if len(candidate) not in (6, 8) or any(char not in "0123456789abcdefABCDEF" for char in candidate):
        raise ValueError(f"Invalid hexadecimal colour: {value}")
    return f"0x{candidate}"


def wrap_overlay(value: str) -> str:
    clean = " ".join(str(value).split()).strip()
    if not clean:
        raise ValueError("Every scene requires non-empty overlay text")
    lines = textwrap.wrap(clean, width=25, break_long_words=False, break_on_hyphens=False)
    if len(lines) > 4:
        lines = lines[:3] + [" ".join(lines[3:])]
    return "\n".join(lines)


def render_scene(
    scene_number: int,
    image_path: Path,
    audio_path: Path,
    overlay_file: Path,
    brand_file: Path,
    output_path: Path,
    duration: float,
    width: int,
    height: int,
    fps: int,
    font_path: str,
    accent: str,
) -> None:
    fade_out = max(0.0, duration - 0.28)
    headline_size = 68 if overlay_file.stat().st_size < 75 else 58
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='min(zoom+0.00045,1.075)':d=1:s={width}x{height}:fps={fps},"
        "eq=saturation=0.92:contrast=1.04,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.20:t=fill,"
        f"drawtext=fontfile='{font_path}':textfile='{overlay_file}':expansion=none:"
        f"fontcolor=white:fontsize={headline_size}:line_spacing=18:"
        "x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.46:boxborderw=30,"
        f"drawtext=fontfile='{font_path}':textfile='{brand_file}':expansion=none:"
        f"fontcolor={accent}:fontsize=34:x=(w-text_w)/2:y=h-165,"
        f"fade=t=out:st={fade_out:.3f}:d=0.28,format=yuv420p"
    )
    audio_filter = (
        "loudnorm=I=-16:LRA=11:TP=-1.5,"
        f"apad,atrim=0:{duration:.3f},"
        "afade=t=in:st=0:d=0.08,"
        f"afade=t=out:st={max(0.0, duration - 0.18):.3f}:d=0.18"
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(image_path),
            "-i",
            str(audio_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            video_filter,
            "-af",
            audio_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(output_path),
        ]
    )
    scene_info = probe(output_path)
    if not has_stream(scene_info, "video") or not has_stream(scene_info, "audio"):
        raise RuntimeError(f"Scene {scene_number} failed audio/video validation")


def mix_music(input_path: Path, music_path: Path, output_path: Path, volume: float) -> None:
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-filter_complex",
            f"[1:a]volume={volume:.3f}[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )


def validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    voice_provider = str(manifest.get("voice_provider", "ElevenLabs")).strip().lower()
    if voice_provider != "elevenlabs":
        raise ValueError("Production voice_provider must be ElevenLabs")
    scenes = manifest.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 5:
        raise ValueError("The renderer requires exactly five scenes")
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {index} must be an object")
        for field in ("image", "voiceover", "overlay"):
            if not str(scene.get(field, "")).strip():
                raise ValueError(f"Scene {index} is missing {field}")
    if str(scenes[-1].get("role", "cta")).lower() != "cta":
        raise ValueError("Scene five must have role 'cta'")
    return scenes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="Local path or HTTPS URL to the render manifest")
    parser.add_argument("output", help="Destination MP4 path")
    parser.add_argument("--report", help="Validation report path")
    args = parser.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")

    manifest = load_json(args.manifest)
    scenes = validate_manifest(manifest)
    width = int(manifest.get("width", 1080))
    height = int(manifest.get("height", 1920))
    fps = int(manifest.get("fps", 30))
    if (width, height) != (1080, 1920):
        raise ValueError("Production output is locked to 1080x1920")
    if fps != 30:
        raise ValueError("Production output is locked to 30 fps")

    style = manifest.get("style") or {}
    font_path = str(style.get("font_path") or DEFAULT_FONT)
    if not Path(font_path).is_file():
        raise ValueError(f"Font does not exist: {font_path}")
    accent = safe_colour(style.get("accent", "D4AF37"), "D4AF37")
    brand = " ".join(str(manifest.get("brand", "THEBUILT")).split()).upper()
    if not brand:
        raise ValueError("Brand is required")

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).resolve() if args.report else output.with_suffix(".report.json")

    with tempfile.TemporaryDirectory(prefix="thebuilt-render-") as temp_name:
        temp = Path(temp_name)
        rendered: list[Path] = []
        scene_report: list[dict[str, Any]] = []
        brand_file = temp / "brand.txt"
        brand_file.write_text(brand, encoding="utf-8")

        for index, scene in enumerate(scenes, start=1):
            image_path = download(str(scene["image"]), temp / f"scene-{index:02d}-image")
            voice_path = download(str(scene["voiceover"]), temp / f"scene-{index:02d}-voice")
            image_info = probe(image_path)
            voice_info = probe(voice_path)
            if not has_stream(image_info, "video"):
                raise ValueError(f"Scene {index} image is not a readable visual asset")
            if not has_stream(voice_info, "audio"):
                raise ValueError(f"Scene {index} voiceover is not a readable audio asset")
            voice_duration = duration_seconds(voice_info)
            requested = float(scene.get("duration", 0) or 0)
            scene_duration = max(2.0, voice_duration + 0.40, requested)
            if scene_duration > 12.0:
                raise ValueError(f"Scene {index} exceeds the 12-second quality limit")

            overlay_file = temp / f"scene-{index:02d}-overlay.txt"
            overlay_file.write_text(wrap_overlay(str(scene["overlay"])), encoding="utf-8")
            scene_output = temp / f"scene-{index:02d}.mp4"
            render_scene(
                index,
                image_path,
                voice_path,
                overlay_file,
                brand_file,
                scene_output,
                scene_duration,
                width,
                height,
                fps,
                font_path,
                accent,
            )
            rendered.append(scene_output)
            scene_report.append(
                {
                    "scene": index,
                    "role": scene.get("role", "body"),
                    "voiceover_duration": round(voice_duration, 3),
                    "rendered_duration": round(duration_seconds(probe(scene_output)), 3),
                    "image_bytes": image_path.stat().st_size,
                    "voiceover_bytes": voice_path.stat().st_size,
                }
            )

        concat_file = temp / "concat.txt"
        concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in rendered), encoding="utf-8")
        silent_music_output = temp / "joined.mp4"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(silent_music_output),
            ]
        )

        music = str(manifest.get("music", "")).strip()
        if music:
            music_path = download(music, temp / "music")
            if not has_stream(probe(music_path), "audio"):
                raise ValueError("Music asset has no audio stream")
            mix_music(silent_music_output, music_path, output, float(manifest.get("music_volume", 0.08)))
        else:
            shutil.copy2(silent_music_output, output)

    final_info = probe(output)
    video_streams = [stream for stream in final_info.get("streams", []) if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in final_info.get("streams", []) if stream.get("codec_type") == "audio"]
    final_duration = duration_seconds(final_info)
    errors: list[str] = []
    if len(video_streams) != 1:
        errors.append("expected_one_video_stream")
    if len(audio_streams) != 1:
        errors.append("expected_one_audio_stream")
    if video_streams and (video_streams[0].get("width"), video_streams[0].get("height")) != (1080, 1920):
        errors.append("invalid_dimensions")
    if not 10 <= final_duration <= 60:
        errors.append("duration_outside_10_to_60_seconds")
    if output.stat().st_size < 500_000:
        errors.append("output_file_suspiciously_small")

    report = {
        "passed": not errors,
        "errors": errors,
        "brand": brand,
        "scene_count": len(scenes),
        "image_count": len(scenes),
        "voiceover_count": len(scenes),
        "voice_provider": "ElevenLabs",
        "source_voiceover_format": "ElevenLabs output (MP3 accepted)",
        "delivery_audio_codec": "AAC inside the social MP4 container",
        "cta_scene": 5,
        "width": video_streams[0].get("width") if video_streams else None,
        "height": video_streams[0].get("height") if video_streams else None,
        "duration": round(final_duration, 3),
        "bytes": output.stat().st_size,
        "video_codec": video_streams[0].get("codec_name") if video_streams else None,
        "audio_codec": audio_streams[0].get("codec_name") if audio_streams else None,
        "scenes": scene_report,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if errors:
        raise RuntimeError("Final render failed validation: " + ", ".join(errors))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RENDER_FAILED: {error}", file=sys.stderr)
        raise

#!/usr/bin/env python3
"""Generate cached DataHot narration audio with a local Qwen3-TTS Base model."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from lite_data import is_list_eligible
from tts_text import DEFAULT_MAX_CHARACTERS, TEXT_VERSION, build_tts_script, narration_hash


ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TZ = timezone(timedelta(hours=8))
DEFAULT_VOICE_VERSION = "datahot-anchor-v1"
MANIFEST_VERSION = 1
AUDIO_PATH_RE = re.compile(
    r"^audio/\d{4}/\d{2}/[a-f0-9]{12}-[a-f0-9]{12,64}\.mp3$"
)


@dataclass(frozen=True)
class NarrationJob:
    event_id: str
    text: str
    content_hash: str
    audio_path: str
    published: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def empty_manifest(voice_version: str) -> dict:
    return {
        "version": MANIFEST_VERSION,
        "voice_version": voice_version,
        "text_version": TEXT_VERSION,
        "updated_at": None,
        "items": {},
    }


def load_manifest(path: Path, voice_version: str) -> dict:
    if not path.exists():
        return empty_manifest(voice_version)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_manifest(voice_version)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), dict):
        return empty_manifest(voice_version)
    if payload.get("voice_version") != voice_version or payload.get("text_version") != TEXT_VERSION:
        return empty_manifest(voice_version)
    payload["version"] = MANIFEST_VERSION
    return payload


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _event_date(event: dict) -> datetime:
    raw = event.get("published") or event.get("first_seen") or ""
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(timezone.utc)


def _audio_relative_path(event: dict, content_hash: str) -> str:
    value = _event_date(event).astimezone(TZ)
    return f"audio/{value:%Y/%m}/{event['event_id']}-{content_hash[:16]}.mp3"


def _ready_entry_matches(entry: object, content_hash: str, site_root: Path) -> bool:
    if not isinstance(entry, dict) or entry.get("status") != "ready":
        return False
    audio_path = str(entry.get("audio_path") or "")
    return bool(
        entry.get("content_hash") == content_hash
        and AUDIO_PATH_RE.fullmatch(audio_path)
        and (site_root / audio_path).is_file()
    )


def select_jobs(
    events: Iterable[dict],
    manifest: dict,
    site_root: Path,
    voice_version: str,
    maximum: int = DEFAULT_MAX_CHARACTERS,
    max_events: int = 8,
) -> list[NarrationJob]:
    candidates = [event for event in events if is_list_eligible(event)]
    candidates.sort(key=_event_date, reverse=True)
    jobs = []
    items = manifest.get("items", {})
    for event in candidates:
        event_id = str(event.get("event_id") or "")
        if not re.fullmatch(r"[a-f0-9]{12}", event_id):
            continue
        text = build_tts_script(event, maximum=maximum)
        if len(text) < 80:
            continue
        content_hash = narration_hash(text, voice_version)
        if _ready_entry_matches(items.get(event_id), content_hash, site_root):
            continue
        jobs.append(NarrationJob(
            event_id=event_id,
            text=text,
            content_hash=content_hash,
            audio_path=_audio_relative_path(event, content_hash),
            published=str(event.get("published") or event.get("first_seen") or ""),
        ))
        if len(jobs) >= max(0, max_events):
            break
    return jobs


def _safe_audio_file(site_root: Path, relative: str) -> Path | None:
    if not AUDIO_PATH_RE.fullmatch(relative):
        return None
    root = site_root.resolve()
    candidate = (site_root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def prune_expired(
    manifest: dict,
    site_root: Path,
    retention_days: int,
    now: datetime | None = None,
) -> list[str]:
    cutoff = (now or utc_now()) - timedelta(days=max(1, retention_days))
    removed = []
    for event_id, entry in list(manifest.get("items", {}).items()):
        try:
            generated = datetime.fromisoformat(str(entry.get("generated_at") or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        if generated >= cutoff:
            continue
        audio_file = _safe_audio_file(site_root, str(entry.get("audio_path") or ""))
        if audio_file and audio_file.exists():
            audio_file.unlink()
        manifest["items"].pop(event_id, None)
        removed.append(event_id)
    return removed


class QwenVoiceCloneBackend:
    def __init__(
        self,
        model_source: str,
        reference_audio: Path,
        reference_text: str,
        device: str = "auto",
    ) -> None:
        import soundfile as sf
        import torch
        from qwen_tts import Qwen3TTSModel

        if device == "auto":
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda:0"
            else:
                device = "cpu"
        dtype = torch.float16 if device != "cpu" else torch.float32
        self._sf = sf
        self.model = Qwen3TTSModel.from_pretrained(
            model_source,
            device_map=device,
            dtype=dtype,
            attn_implementation="sdpa",
        )
        self.prompt = self.model.create_voice_clone_prompt(
            ref_audio=str(reference_audio),
            ref_text=reference_text,
            x_vector_only_mode=False,
        )

    def synthesize(self, text: str, output_wav: Path) -> float:
        wavs, sample_rate = self.model.generate_voice_clone(
            text=text,
            language="Chinese",
            voice_clone_prompt=self.prompt,
            non_streaming_mode=True,
        )
        self._sf.write(output_wav, wavs[0], sample_rate)
        return len(wavs[0]) / sample_rate


def encode_mp3(input_wav: Path, output_mp3: Path, bitrate: str = "64k") -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to encode narration audio")
    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(input_wav),
        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
        "-ac", "1", "-ar", "24000", "-b:a", bitrate, str(output_mp3),
    ], check=True)


def process_jobs(
    jobs: Iterable[NarrationJob],
    manifest: dict,
    site_root: Path,
    backend: QwenVoiceCloneBackend,
    voice_version: str,
    bitrate: str = "64k",
    now: Callable[[], datetime] = utc_now,
) -> tuple[int, int]:
    completed = failed = 0
    for job in jobs:
        target = _safe_audio_file(site_root, job.audio_path)
        if target is None:
            raise ValueError(f"unsafe audio path: {job.audio_path}")
        try:
            with tempfile.TemporaryDirectory(prefix="datahot-tts-") as directory:
                wav_path = Path(directory) / "speech.wav"
                mp3_path = Path(directory) / "speech.mp3"
                duration = backend.synthesize(job.text, wav_path)
                encode_mp3(wav_path, mp3_path, bitrate=bitrate)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(mp3_path), target)
            manifest["items"][job.event_id] = {
                "status": "ready",
                "content_hash": job.content_hash,
                "audio_path": job.audio_path,
                "duration_seconds": round(duration, 1),
                "characters": len(job.text),
                "generated_at": now().isoformat(),
                "voice_version": voice_version,
                "text_version": TEXT_VERSION,
            }
            completed += 1
            print(f"[tts] ready {job.event_id}: {duration:.1f}s -> {job.audio_path}")
        except Exception as error:  # individual failures must not block other articles
            failed += 1
            print(f"[tts] failed {job.event_id}: {type(error).__name__}: {error}")
    return completed, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=SITE / "data" / "latest.json")
    parser.add_argument("--manifest", type=Path, default=SITE / "data" / "tts-manifest.json")
    parser.add_argument("--site-root", type=Path, default=SITE)
    parser.add_argument("--voice-version", default=os.getenv("TTS_VOICE_VERSION", DEFAULT_VOICE_VERSION))
    parser.add_argument("--max-events", type=int, default=int(os.getenv("TTS_MAX_EVENTS_PER_RUN", "8")))
    parser.add_argument("--max-characters", type=int, default=int(os.getenv("TTS_MAX_CHARACTERS", str(DEFAULT_MAX_CHARACTERS))))
    parser.add_argument("--retention-days", type=int, default=int(os.getenv("TTS_RETENTION_DAYS", "30")))
    parser.add_argument("--bitrate", default=os.getenv("TTS_AUDIO_BITRATE", "64k"))
    parser.add_argument("--model-source", default=os.getenv("TTS_MODEL_PATH", ""))
    parser.add_argument("--reference-audio", type=Path, default=Path(os.getenv("TTS_REFERENCE_AUDIO", ".")))
    parser.add_argument("--reference-text-file", type=Path, default=Path(os.getenv("TTS_REFERENCE_TEXT_FILE", ".")))
    parser.add_argument("--device", default=os.getenv("TTS_DEVICE", "auto"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data.read_text(encoding="utf-8"))
    manifest = load_manifest(args.manifest, args.voice_version)
    jobs = select_jobs(
        payload.get("events", []), manifest, args.site_root, args.voice_version,
        maximum=args.max_characters, max_events=args.max_events,
    )
    if args.dry_run:
        print(json.dumps({
            "voice_version": args.voice_version,
            "jobs": [job.__dict__ for job in jobs],
        }, ensure_ascii=False, indent=2))
        return 0

    if not jobs:
        removed = [] if args.no_cleanup else prune_expired(
            manifest, args.site_root, args.retention_days,
        )
        manifest["updated_at"] = utc_now().isoformat()
        write_manifest(args.manifest, manifest)
        print(f"[tts] completed=0 failed=0 pruned={len(removed)}")
        return 0

    if not args.model_source:
        raise SystemExit("--model-source or TTS_MODEL_PATH is required")
    if not args.reference_audio.is_file() or not args.reference_text_file.is_file():
        raise SystemExit("reference audio and transcript files are required")
    reference_text = args.reference_text_file.read_text(encoding="utf-8").strip()
    if not reference_text:
        raise SystemExit("reference transcript is empty")

    backend = QwenVoiceCloneBackend(
        args.model_source, args.reference_audio, reference_text, device=args.device,
    )
    completed, failed = process_jobs(
        jobs, manifest, args.site_root, backend, args.voice_version, bitrate=args.bitrate,
    )
    removed = [] if args.no_cleanup else prune_expired(
        manifest, args.site_root, args.retention_days,
    )
    manifest["updated_at"] = utc_now().isoformat()
    write_manifest(args.manifest, manifest)
    print(f"[tts] completed={completed} failed={failed} pruned={len(removed)}")
    return 1 if failed and not completed else 0


if __name__ == "__main__":
    raise SystemExit(main())

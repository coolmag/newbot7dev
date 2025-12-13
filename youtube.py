from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import logging

logger = logging.getLogger("youtube")


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    webpage_url: str
    duration: Optional[int] = None  # seconds


STOP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b24/7\b", re.IGNORECASE),
    # ВАЖНО: прежнее 'udio' ломает 'Audio', 'Audioslave'. Делаем точное слово Udio.
    re.compile(r"\budio\b", re.IGNORECASE),
    re.compile(r"\blive\b", re.IGNORECASE),
]


def _is_blocked(title: str) -> bool:
    t = title.strip()
    return any(p.search(t) for p in STOP_PATTERNS)


async def _run_subprocess(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """
    Запускает subprocess в отдельной process group.
    При таймауте убивает всю группу (иначе yt-dlp иногда висит дочерними процессами).
    """
    logger.debug("Run: %s", " ".join(shlex.quote(x) for x in cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=os.setsid if os.name != "nt" else None,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Timeout running: %s", cmd[:4])
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
        else:
            proc.kill()
        raise
    return proc.returncode, out_b.decode("utf-8", "replace"), err_b.decode("utf-8", "replace")


def _cookies_args(cookies_path: str) -> list[str]:
    if cookies_path and Path(cookies_path).exists():
        return ["--cookies", cookies_path]
    return []


async def yt_search(
    query: str,
    max_results: int,
    timeout_sec: int,
    cookies_path: str = "",
) -> List[Track]:
    """
    Поиск через yt-dlp без YouTube API: ytsearchN:query + --dump-json.
    """
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--dump-json",
        "--no-playlist",
        "--flat-playlist",
        "--quiet",
        "--no-warnings",
        "--socket-timeout", "10",
        "--retries", "2",
        f"ytsearch{max_results}:{query}",
    ] + _cookies_args(cookies_path)

    code, out, err = await _run_subprocess(cmd, timeout=timeout_sec)
    if code != 0:
        logger.warning("yt_search failed code=%s err=%s", code, err[-400:])
        return []

    tracks: list[Track] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            vid = data.get("id")
            title = data.get("title") or ""
            url = data.get("url") or data.get("webpage_url")
            if not vid or not title:
                continue
            if _is_blocked(title):
                continue
            webpage_url = url if (url and url.startswith("http")) else f"https://www.youtube.com/watch?v={vid}"
            tracks.append(Track(id=vid, title=title, webpage_url=webpage_url, duration=data.get("duration")))
        except Exception:
            continue

    # уникальность по id
    uniq: dict[str, Track] = {}
    for t in tracks:
        uniq.setdefault(t.id, t)
    return list(uniq.values())


async def download_audio_mp3(
    track: Track,
    timeout_sec: int,
    max_filesize_mb: int,
    cookies_path: str = "",
) -> Path:
    """
    Скачивает и извлекает mp3 в tmp dir. Возвращает путь к файлу.
    Важно: обёрнуто в таймаут и убивает процесс при зависании.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="musicbot_"))
    outtmpl = str(tmpdir / f"{track.id}.%(ext)s")

    cmd = [
        "yt-dlp",
        track.webpage_url,
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--max-filesize", f"{max_filesize_mb}M",
        "--socket-timeout", "10",
        "--retries", "2",
        "--fragment-retries", "2",
        "--concurrent-fragments", "1",
        "--no-progress",
        "--quiet",
        "--no-warnings",
        "-o", outtmpl,
    ] + _cookies_args(cookies_path)

    code, out, err = await _run_subprocess(cmd, timeout=timeout_sec)
    if code != 0:
        # чистим мусор
        for p in tmpdir.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            tmpdir.rmdir()
        except Exception:
            pass
        raise RuntimeError(f"yt-dlp download failed: {err[-500:]}")

    # найдём mp3
    mp3s = list(tmpdir.glob(f"{track.id}.mp3"))
    if not mp3s:
        # иногда расширение другое — найдём любой файл по id
        any_files = list(tmpdir.glob(f"{track.id}.*"))
        if not any_files:
            raise RuntimeError("Downloaded file not found")
        return any_files[0]
    return mp3s[0]
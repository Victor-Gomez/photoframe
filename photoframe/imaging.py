"""Reading photo headers, and turning a photo into the pixels a screen actually shows.

Nothing here writes next to the originals, or anywhere else on disk: renders are made per
request and kept in memory only. avifdec's intermediate JPEG is the one file written, into
the system temp directory, and it is deleted in the same call.
"""

import io
import logging
import os
import random
import re
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

# Originals are always served byte for byte, so the library is limited to the formats a
# browser renders itself. HEIC, TIFF and BMP are left out of the index entirely rather than
# transcoded — Chrome cannot display them, and nothing here re-encodes anything.
SOURCE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".avif": "image/avif",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
EXTENSIONS = set(SOURCE_MIME)

# A ceiling on what a client may ask to be rendered, so a stray query parameter cannot make
# the server allocate an enormous image. Not a setting: there is nothing to tune.
MAX_RENDER_EDGE = 4096

_XMP_SUBJECT = re.compile(rb"<dc:subject[^>]*>(.*?)</dc:subject>", re.S)
_XMP_ITEM = re.compile(rb"<rdf:li[^>]*>(.*?)</rdf:li>", re.S)


def lowered(tags) -> tuple[str, ...]:
    return tuple(str(tag).strip().lower() for tag in tags if str(tag).strip())


def tags_of(im: Image.Image) -> list[str]:
    """Keywords from the XMP packet — `dc:subject`, what most taggers write.

    The packet rides along with the header read, so this costs nothing extra.
    """
    packet = im.info.get("xmp")
    if not packet:
        return []
    found = _XMP_SUBJECT.search(packet)
    if not found:
        return []
    items = [item.strip() for item in _XMP_ITEM.findall(found.group(1))]
    return [tag for tag in (i.decode("utf-8", "replace").strip() for i in items) if tag]


def probe(path: Path) -> tuple[float, list[str]]:
    """Aspect ratio and tags, from the header only — the file is never decoded."""
    with Image.open(path) as im:
        width, height = im.size
        if im.getexif().get(274, 1) >= 5:  # EXIF orientation swaps width and height
            width, height = height, width
        return (width / height if height else 1.0), tags_of(im)


class RenderCache:
    """Rendered JPEGs, most recently used last. Memory only — never written to disk.

    Re-viewing a photo — stepping back and forward, or scrolling the gallery over the same
    burst — is the case this exists for. A photo seen for the first time still pays the
    full decode; nothing can avoid that.
    """

    def __init__(self, budget_bytes: int):
        self.budget = budget_bytes
        self._entries: "OrderedDict[tuple, bytes]" = OrderedDict()
        self._lock = threading.Lock()
        self._bytes = 0
        self.hits = self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key) -> bool:
        with self._lock:
            return key in self._entries

    @property
    def nbytes(self) -> int:
        with self._lock:
            return self._bytes

    @staticmethod
    def key(source: Path, width: int, height: int):
        """Includes the file's own stamp, so a photo replaced by the sync is never stale."""
        try:
            stat = source.stat()
        except OSError:
            return None
        return (str(source), width, height, stat.st_mtime_ns, stat.st_size)

    def get(self, key) -> bytes | None:
        if key is None or not self.budget:
            return None
        with self._lock:
            data = self._entries.get(key)
            if data is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)  # freshly used, so last to be evicted
            self.hits += 1
            return data

    def put(self, key, data: bytes) -> None:
        if key is None or not self.budget or len(data) > self.budget:
            return
        with self._lock:
            if key in self._entries:
                self._bytes -= len(self._entries.pop(key))
            self._entries[key] = data
            self._bytes += len(data)
            while self._bytes > self.budget and self._entries:
                self._bytes -= len(self._entries.popitem(last=False)[1])

    def stats(self) -> dict:
        with self._lock:
            looked_up = self.hits + self.misses
            return {
                "entries": len(self._entries),
                "mb": round(self._bytes / 1048576, 1),
                "budgetMB": self.budget // 1048576,
                "hits": self.hits,
                "misses": self.misses,
                "hitRate": f"{self.hits / looked_up:.0%}" if looked_up else "n/a",
            }


class Renderer:
    """Scales and crops to exactly the size asked for, by whichever decoder is quicker.

    Two decoders rather than one because which is faster is not obvious and changes with
    the file: `avifdecShare` sends a fraction of renders down each path so they can be
    compared on real traffic rather than on a benchmark. See /api/render-stats.
    """

    SAMPLES = 500

    def __init__(self, settings, cache: RenderCache):
        self.quality = settings.jpeg_quality
        self.avifdec = settings.avifdec
        self.avifdec_share = settings.avifdec_share
        self.avifdec_timeout = settings.avifdec_timeout
        self.cache = cache
        # Each in-flight encode holds a full decoded photo, so the number of them is capped
        # well below the pool of request threads: decoding a 24 MP photo needs a few hundred
        # MB for a moment, and eight at once is how the server itself falls over.
        self.slots = threading.Semaphore(settings.encode_threads)
        self._times: dict[str, list[float]] = {"pillow": [], "avifdec": []}
        self._times_lock = threading.Lock()

    def render(self, source: Path, width: int, height: int) -> bytes:
        """The cached JPEG if there is one, otherwise a fresh one, remembered on the way out."""
        # Looked up before the semaphore: a hit costs nothing, and queueing it behind real
        # renders would throw away the whole point of having a cache.
        key = RenderCache.key(source, width, height)
        data = self.cache.get(key)
        if data is not None:
            return data
        with self.slots:
            data = self.cache.get(key)   # another thread may have rendered it while we queued
            if data is None:
                data = self._encode(source, width, height).getvalue()
                self.cache.put(key, data)
        return data

    def _encode(self, source: Path, width: int, height: int) -> io.BytesIO:
        use_avifdec = (
            self.avifdec
            and source.suffix.lower() == ".avif"
            and random.random() < self.avifdec_share
        )
        started = time.perf_counter()
        try:
            result = (self._with_avifdec if use_avifdec else self._with_pillow)(
                source, width, height)
        except Exception:
            if not use_avifdec:
                raise
            log.exception("avifdec failed on %s; falling back to Pillow", source)
            result = self._with_pillow(source, width, height)
            use_avifdec = False
        self._record("avifdec" if use_avifdec else "pillow",
                     (time.perf_counter() - started) * 1000)
        return result

    def _fit_and_encode(self, im: Image.Image, width: int, height: int) -> io.BytesIO:
        # The orientation lives in EXIF and is lost on re-encode, so apply it first.
        im = ImageOps.exif_transpose(im)
        fitted = ImageOps.fit(im, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))
        buffer = io.BytesIO()
        fitted.convert("RGB").save(
            buffer, "JPEG", quality=self.quality, optimize=True, progressive=True)
        buffer.seek(0)
        return buffer

    def _with_pillow(self, source: Path, width: int, height: int) -> io.BytesIO:
        with Image.open(source) as im:
            return self._fit_and_encode(im, width, height)

    def _with_avifdec(self, source: Path, width: int, height: int) -> io.BytesIO:
        """Decode with avifdec into a temporary JPEG, then scale that.

        The intermediate is deliberately JPEG rather than PNG: it is a tenth of the bytes to
        write and read, and Pillow's `draft` can then decode it at a reduced DCT scale,
        which costs almost nothing. It lives in the system temp directory and is deleted
        straight away — nothing is ever written next to the photos.
        """
        handle, temporary = tempfile.mkstemp(suffix=".jpg", prefix="photoframe-")
        os.close(handle)
        temporary = Path(temporary)
        try:
            # subprocess.run kills the child if the timeout expires, so the slot is released
            # either way. TimeoutExpired is an Exception, so _encode falls back to Pillow.
            subprocess.run(
                [self.avifdec, "-j", "all", "-q", "92", str(source), str(temporary)],
                check=True,
                capture_output=True,
                timeout=self.avifdec_timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with Image.open(temporary) as im:
                im.draft("RGB", (width, height))  # decode at a reduced scale where it can
                return self._fit_and_encode(im, width, height)
        finally:
            temporary.unlink(missing_ok=True)

    def _record(self, method: str, milliseconds: float) -> None:
        with self._times_lock:
            samples = self._times.setdefault(method, [])
            samples.append(milliseconds)
            del samples[:-self.SAMPLES]  # a rolling window, not a growing list

    def stats(self) -> dict:
        """How the two decoders are actually doing, over the last few hundred renders each."""
        with self._times_lock:
            samples = {name: sorted(times) for name, times in self._times.items()}

        def summarise(times: list[float]) -> dict:
            if not times:
                return {"renders": 0}
            return {
                "renders": len(times),
                "medianMs": round(times[len(times) // 2]),
                "meanMs": round(sum(times) / len(times)),
                "p90Ms": round(times[min(len(times) - 1, int(len(times) * 0.9))]),
                "fastestMs": round(times[0]),
                "slowestMs": round(times[-1]),
            }

        report = {name: summarise(times) for name, times in samples.items()}
        measured = [r for r in report.values() if r.get("renders")]
        if len(measured) == 2 and all(r["renders"] >= 20 for r in report.values()):
            pillow, avifdec = report["pillow"]["medianMs"], report["avifdec"]["medianMs"]
            report["verdict"] = (
                f"avifdec is {abs(pillow - avifdec) / max(pillow, 1):.0%} "
                f"{'faster' if avifdec < pillow else 'slower'} at the median")
        else:
            report["verdict"] = "not enough renders yet (20 each)"
        report["avifdec"] = report.get("avifdec", {"renders": 0})
        report["avifdecShare"] = self.avifdec_share
        report["avifdecPath"] = self.avifdec or "(not configured)"
        report["tempDir"] = tempfile.gettempdir()
        report["cache"] = self.cache.stats()
        return report

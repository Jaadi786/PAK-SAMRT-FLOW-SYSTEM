"""Optional adapters for a real vision stack.

This module is the *only* place a production detector plugs in. Everything
downstream -- evidence sealing, fuzzy risk scoring, the compliance ladder --
consumes a :class:`~smartflow.models.CameraEvent` and does not care whether the
frames came from YOLOv10 or from :mod:`smartflow.scenarios`.

Two seams are provided:

``frames_from_directory``
    Turn real JPEG/PNG files into sealed-ready ``FrameCapture`` objects. Point
    it at a folder of extracted frames and the evidence layer treats them
    exactly like synthetic ones.

``YoloDetector``
    Wraps ``ultralytics`` when it is installed. It never becomes a hard
    dependency: :meth:`YoloDetector.is_available` is checked first and the
    caller keeps the synthetic path when it returns ``False``.

Why this file is short
----------------------
Deliberate. A detector that only works on the presenter's laptop is a demo
liability. The synthetic path always runs, the real path is additive, and the
swap is one function call -- which is also the honest way to describe the
project's readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from smartflow.models import CameraEvent, FrameCapture, ViolationType

#: Map a detector's class names onto the domain's violation types. A real
#: deployment would load this from a config file owned by the traffic authority.
CLASS_TO_VIOLATION: Mapping[str, ViolationType] = {
    "red_light": ViolationType.RED_LIGHT,
    "traffic_light": ViolationType.RED_LIGHT,
    "speeding": ViolationType.OVERSPEEDING,
    "wrong_way": ViolationType.WRONG_WAY,
    "no_helmet": ViolationType.NO_HELMET,
    "no_seatbelt": ViolationType.NO_SEATBELT,
    "mobile_use": ViolationType.MOBILE_USE,
    "lane_violation": ViolationType.LANE_VIOLATION,
    "illegal_parking": ViolationType.ILLEGAL_PARKING,
}

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


class DetectorUnavailable(RuntimeError):
    """Raised when a real detector was requested but cannot run."""


def frames_from_directory(
    directory: str | Path,
    camera_id: str = "CAM-FILE",
    captured_at: datetime | None = None,
    limit: int | None = None,
) -> tuple[FrameCapture, ...]:
    """Load real image files as ``FrameCapture`` objects.

    Payloads are the file bytes, so the SHA-256 digests are genuine digests of
    genuine evidence. This is the fastest path from "we have footage" to "the
    evidence layer works on it".
    """
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    files = sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if limit is not None:
        files = files[:limit]
    if not files:
        raise FileNotFoundError(f"no image files found in {root}")
    base = captured_at or datetime.now().astimezone()
    frames: list[FrameCapture] = []
    for index, path in enumerate(files):
        frames.append(
            FrameCapture(
                index=index,
                captured_at=base + timedelta(milliseconds=250 * index),
                payload=path.read_bytes(),
                camera_id=camera_id,
            )
        )
    return tuple(frames)


@dataclass
class Detection:
    class_name: str
    confidence: float
    box: tuple[float, float, float, float]


class YoloDetector:
    """Thin wrapper over ``ultralytics.YOLO``.

    Present so the seam is explicit and reviewable. It is never imported at
    module load, so the dependency-free core stays dependency-free.
    """

    def __init__(self, weights: str = "yolov10n.pt", device: str | None = None) -> None:
        self.weights = weights
        self.device = device
        self._model = None

    @staticmethod
    def is_available() -> bool:
        try:
            import ultralytics  # noqa: F401
        except ImportError:
            return False
        return True

    def load(self) -> None:
        if not self.is_available():
            raise DetectorUnavailable(
                "ultralytics is not installed. Install the extras "
                "(pip install -r requirements-extras.txt) or keep using the "
                "synthetic frame path, which always works offline."
            )
        from ultralytics import YOLO  # pragma: no cover - optional dependency

        self._model = YOLO(self.weights)

    def detect(self, image_path: str | Path) -> list[Detection]:
        if self._model is None:
            self.load()
        results = self._model.predict(str(image_path), device=self.device, verbose=False)
        detections: list[Detection] = []
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                class_id = int(box.cls[0])
                detections.append(
                    Detection(
                        class_name=str(names.get(class_id, class_id)).lower(),
                        confidence=float(box.conf[0]),
                        box=tuple(float(v) for v in box.xyxy[0]),
                    )
                )
        return detections

    def to_event(
        self,
        detections: Sequence[Detection],
        frames: Sequence[FrameCapture],
        camera_id: str,
        location: str,
        captured_at: datetime,
        traffic_density: float = 40.0,
        context_tags: tuple[str, ...] = (),
        speed_kmh: float | None = None,
        speed_limit_kmh: float | None = None,
        min_confidence: float = 0.5,
    ) -> CameraEvent:
        """Convert raw detections into the domain's ``CameraEvent``.

        Only classes present in :data:`CLASS_TO_VIOLATION` above the confidence
        floor become violations. Unknown classes are ignored rather than
        guessed at -- guessing is how false positives get into an enforcement
        pipeline.
        """
        violations: list[ViolationType] = []
        for detection in sorted(detections, key=lambda d: d.confidence, reverse=True):
            if detection.confidence < min_confidence:
                continue
            violation = CLASS_TO_VIOLATION.get(detection.class_name)
            if violation is not None and violation not in violations:
                violations.append(violation)
        return CameraEvent(
            camera_id=camera_id,
            location=location,
            captured_at=captured_at,
            violations=tuple(violations),
            frames=tuple(frames),
            speed_kmh=speed_kmh,
            speed_limit_kmh=speed_limit_kmh,
            traffic_density=traffic_density,
            context_tags=context_tags,
        )


def frame_digest_summary(frames: Iterable[FrameCapture]) -> list[dict[str, object]]:
    """Quick audit view of what is about to be sealed."""
    from smartflow.evidence import hash_payload

    return [
        {
            "index": frame.index,
            "camera_id": frame.camera_id,
            "captured_at": frame.captured_at.isoformat(),
            "size_bytes": frame.size_bytes,
            "sha256": hash_payload(frame.payload),
        }
        for frame in frames
    ]

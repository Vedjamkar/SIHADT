"""
Error Level Analysis (ELA).

Mechanism
    JPEG is lossy and roughly idempotent: re-saving an already-compressed
    region at the same quality changes it very little, because the DCT
    coefficients have already been quantised to that grid. A region that was
    edited and re-encoded once has a *different* compression history, so
    re-saving it produces a visibly larger error than its surroundings.

    So: re-encode the upload at a fixed quality, subtract it from the original,
    amplify the residual, and look for blocks whose error is anomalous relative
    to the rest of the image.

Read this part before you demo it
    ELA is the weakest signal in the whole app and it is the one most likely to
    embarrass you on stage.
      - It needs a JPEG original. Screenshots, PNGs and anything that has been
        through a messaging app have a uniform compression history and ELA
        returns noise.
      - Sharp edges, printed text and QR modules always show high error. On an
        ID card, that is most of the image.
      - A forger who re-encodes the whole document after editing erases the
        signal entirely. This is a one-line defeat.
    We therefore return a *localisation heatmap plus block statistics* and let
    the verdict engine treat it as advisory only. If a judge asks for accuracy
    numbers, the correct answer is that you have not measured them on a labelled
    dataset, and that ELA is a visual aid for a reviewer rather than a
    classifier. That answer beats an invented percentage.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageChops, ImageEnhance

RESAVE_QUALITY = 90
BLOCK_SIZE = 32

# How many standard deviations above the image's own mean a block must sit
# before it counts as anomalous.
#
# These two constants have to be chosen together, and the previous pair was
# self-defeating. At 2.5 sigma, a normal distribution puts about 0.62% of
# blocks above the threshold by chance alone — that is the null rate, the
# fraction you expect on a completely untouched image. The old
# MIN_FLAGGED_FRACTION was 0.004, i.e. 0.4%, which sits BELOW that null rate,
# so ELA_LOCALISED_ANOMALY fired on essentially every JPEG ever submitted.
#
# At 3.0 sigma the null rate drops to roughly 0.135%. Firing only at 2%
# leaves an order-of-magnitude margin over chance, so a flag means a genuinely
# concentrated region of differing compression history rather than ordinary
# sensor noise or sharp printed text.
#
# Erring toward silence is deliberate. A false accusation costs an honest
# applicant far more than a missed forgery costs us, and ELA is a heuristic
# that cannot, on its own, justify calling anyone a forger.
FLAG_SIGMA = 3.0
MIN_FLAGGED_FRACTION = 0.02


def _looks_like_camera_capture(image: Image.Image) -> bool:
    """
    Does this JPEG look like it came straight out of a camera?

    EXIF is the practical signal. A phone or camera writes Make, Model and
    usually DateTimeOriginal; an image that has been through an editor and
    re-saved has typically lost them, or gained a Software tag naming the
    editor. So a file still carrying camera identification and no editing
    software tag is, to a good approximation, singly-compressed — and ELA has
    nothing to compare within it.

    This is a heuristic about a heuristic, so it is applied in the cautious
    direction only: it can suppress an ELA result, never produce one. The
    failure mode is staying quiet on an image we might have analysed, which is
    the failure mode we want.
    """
    try:
        exif = image.getexif()
    except Exception:
        return False

    if not exif:
        return False

    # EXIF tag numbers: 271 Make, 272 Model, 305 Software.
    make = str(exif.get(271, "") or "").strip()
    model = str(exif.get(272, "") or "").strip()
    software = str(exif.get(305, "") or "").strip().lower()

    if not (make or model):
        return False

    # A Software tag naming a known editor means it was re-saved, so the
    # single-compression assumption no longer holds and ELA is back in play.
    editors = ("photoshop", "gimp", "lightroom", "paint", "snapseed",
               "picsart", "canva", "imagemagick", "pillow")
    if any(name in software for name in editors):
        return False

    return True


@dataclass
class ELAResult:
    applicable: bool
    source_format: str
    mean_error: float
    max_error: float
    flagged_blocks: list[dict]
    flagged_fraction: float
    heatmap_png_base64: str | None
    reasons: list[str]


def analyse(image_bytes: bytes) -> ELAResult:
    # Keep the image as opened: convert("RGB") discards EXIF, and the camera
    # check below needs it.
    opened = Image.open(io.BytesIO(image_bytes))
    source_format = (opened.format or "UNKNOWN").upper()
    original = opened.convert("RGB")

    # Be upfront when the input cannot support the technique.
    if source_format not in {"JPEG", "JPG", "MPO"}:
        return ELAResult(
            applicable=False,
            source_format=source_format,
            mean_error=0.0,
            max_error=0.0,
            flagged_blocks=[],
            flagged_fraction=0.0,
            heatmap_png_base64=None,
            reasons=["ELA_NOT_APPLICABLE_NON_JPEG"],
        )

    # Be equally upfront when the input is a JPEG but still cannot support the
    # technique. ELA works by comparing compression histories BETWEEN regions,
    # which requires the image to have been saved more than once. A photograph
    # taken straight from a camera has exactly one compression history across
    # the whole frame, so there is nothing to compare and any bright region is
    # texture, not tampering.
    #
    # This is the common case for us, not an edge case: photographing a printed
    # document is the primary way documents reach this system, and printing
    # then re-photographing destroys whatever editing history the original had.
    # Reporting applicable=True there invites the operator to read camera noise
    # as evidence.
    if _looks_like_camera_capture(opened):
        return ELAResult(
            applicable=False,
            source_format=source_format,
            mean_error=0.0,
            max_error=0.0,
            flagged_blocks=[],
            flagged_fraction=0.0,
            heatmap_png_base64=None,
            reasons=["ELA_NOT_APPLICABLE_CAMERA_CAPTURE"],
        )

    buffer = io.BytesIO()
    original.save(buffer, "JPEG", quality=RESAVE_QUALITY)
    buffer.seek(0)
    resaved = Image.open(buffer).convert("RGB")

    difference = ImageChops.difference(original, resaved)
    extrema = difference.getextrema()
    max_channel = max(channel[1] for channel in extrema) or 1
    scale = 255.0 / max_channel
    heatmap = ImageEnhance.Brightness(difference).enhance(scale)

    residual = np.asarray(difference, dtype=np.float32).mean(axis=2)
    # First element is the total block count, which nothing reads.
    _, flagged, flagged_fraction = _score_blocks(residual)

    reasons: list[str] = []
    if flagged_fraction >= MIN_FLAGGED_FRACTION:
        reasons.append("ELA_LOCALISED_ANOMALY")
    else:
        reasons.append("ELA_NO_LOCALISED_ANOMALY")

    return ELAResult(
        applicable=True,
        source_format=source_format,
        mean_error=float(residual.mean()),
        max_error=float(residual.max()),
        flagged_blocks=flagged,
        flagged_fraction=flagged_fraction,
        heatmap_png_base64=_encode_png(heatmap),
        reasons=reasons,
    )


def _score_blocks(residual: np.ndarray) -> tuple[int, list[dict], float]:
    """
    Tile the residual and flag blocks whose mean error is an outlier.

    Comparing each block against the image's own distribution matters. An
    absolute threshold fails immediately: a phone photo under bad light has a
    high error floor everywhere, and a clean scan has a low one. Relative
    outliers survive both.
    """
    height, width = residual.shape
    rows = max(height // BLOCK_SIZE, 1)
    columns = max(width // BLOCK_SIZE, 1)

    means = np.zeros((rows, columns), dtype=np.float32)
    for row in range(rows):
        for column in range(columns):
            patch = residual[
                row * BLOCK_SIZE : (row + 1) * BLOCK_SIZE,
                column * BLOCK_SIZE : (column + 1) * BLOCK_SIZE,
            ]
            means[row, column] = patch.mean() if patch.size else 0.0

    mean = float(means.mean())
    deviation = float(means.std()) or 1.0
    threshold = mean + FLAG_SIGMA * deviation

    flagged = [
        {
            "x": int(column * BLOCK_SIZE),
            "y": int(row * BLOCK_SIZE),
            "w": BLOCK_SIZE,
            "h": BLOCK_SIZE,
            "error": round(float(means[row, column]), 3),
            "z_score": round((float(means[row, column]) - mean) / deviation, 2),
        }
        for row in range(rows)
        for column in range(columns)
        if means[row, column] > threshold
    ]
    flagged.sort(key=lambda block: block["z_score"], reverse=True)

    total = rows * columns
    return total, flagged[:40], len(flagged) / total if total else 0.0


def _encode_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()

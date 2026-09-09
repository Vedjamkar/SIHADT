"""
Image forensics beyond ELA.

Why this module exists
----------------------
ELA was the only tamper signal in this project, and it is the weakest one
available: it needs a JPEG that still carries its editing history, it fires
readily on sharp printed text, and photographing a printed document destroys
the evidence it depends on. Leaning on it alone was the single biggest gap
between what the system claimed and what it could support.

Each detector here answers a different, narrower question, and each one is
independently defensible:

    detect_screen_replay      Was this photographed off a screen?
    detect_copy_move          Was a region of this image duplicated?
    detect_noise_inconsistency Do different regions have different sensor noise?
    inspect_metadata          Does the file's own metadata contradict it?

What this module is NOT
-----------------------
**It is not a deepfake detector.** Nothing here decides whether a face was
synthesised. A real one needs a trained model — a presentation-attack
detection (PAD) network or a synthesis-artifact classifier — and training or
shipping one is out of scope. Saying so plainly is worth more than a
convincing-looking score, and the project has consistently chosen that trade.

What `detect_screen_replay` does cover is the most common *practical* attack
in a live-capture setting: holding a phone or laptop displaying an image, or
a deepfake video, up to the camera. That is a real and useful narrowing —
but a deepfake fed directly into a virtual camera bypasses it entirely, and
it must never be described as deepfake detection.

Every signal here is HEURISTIC tier. None may decide a verdict on its own;
that rule is enforced in verdict.assess(), which requires two independent
heuristic signals before it will even ask for human review. That is
deliberate: a false accusation costs an honest applicant far more than a
missed forgery costs us.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

# Analysis is done on a downscaled copy. These detectors look at structure and
# statistics, not fine detail, and full-resolution phone photos make the FFT
# and the block matching needlessly slow.
WORKING_EDGE = 512

# ---------------------------------------------------------------------------
# Screen replay / moire
# ---------------------------------------------------------------------------

# A camera pointed at an LCD samples the display's pixel grid, and the two
# regular grids beat against each other. That interference is periodic, so it
# shows up in the frequency domain as isolated peaks well away from the
# centre — unlike natural image content, whose spectrum falls off smoothly.
MOIRE_PEAK_SIGMA = 8.0        # how far above the local mean a peak must sit
MOIRE_MIN_PEAKS = 4           # isolated peaks needed before we say anything
MOIRE_LOW_FREQ_EXCLUDE = 0.12 # ignore the DC region, which is always bright
MOIRE_HIGH_FREQ_EXCLUDE = 0.95  # ignore the extreme corners: resampling noise

# Exclude a band along both spectrum axes.
#
# This is the correction that made the detector usable. A first version
# flagged every genuine card front, because a document is FULL of legitimate
# periodic structure — text baselines, ruled lines, card edges, the QR itself.
# All of that regular horizontal and vertical structure puts its energy on the
# axes of the spectrum.
#
# Screen moire is different: it is the beat between two grids at an angle to
# each other, so its peaks sit OFF the axes. Excluding the axis cross keeps
# the thing we want and drops the thing that was causing false accusations.
MOIRE_AXIS_EXCLUDE = 0.06


@dataclass
class ScreenReplayResult:
    checked: bool
    likely_screen: bool
    peak_count: int
    peak_strength: float
    reasons: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def detect_screen_replay(image_bytes: bytes) -> ScreenReplayResult:
    """
    Look for the periodic interference left by photographing a screen.

    This is the practical presentation attack: someone holds a phone showing
    a stored image — or a deepfake video — up to the camera. The display's
    pixel grid beats against the camera's sensor grid and leaves moire, which
    is periodic, which is visible as isolated peaks in the FFT magnitude
    spectrum.

    Limits, stated because they matter:
      * A high-quality capture at the right distance and angle can avoid
        visible moire entirely.
      * A deepfake injected through a virtual camera never touches a screen,
        so this sees nothing at all.
      * Some genuine documents carry fine regular security patterns
        (guilloche, microprint) which are themselves periodic. That is why
        the threshold is deliberately conservative and the result is
        advisory.
    """
    try:
        image = _load_grayscale(image_bytes)
    except Exception as exc:
        return ScreenReplayResult(
            checked=False, likely_screen=False, peak_count=0, peak_strength=0.0,
            reasons=["SCREEN_REPLAY_NOT_CHECKED"],
            detail={"error": str(exc)[:200]},
        )

    array = np.asarray(image, dtype=np.float32) / 255.0

    # Window the image before the FFT. Without it, the discontinuity at the
    # image edges produces a bright cross through the spectrum that looks
    # exactly like the periodic peaks we are hunting for.
    window = np.hanning(array.shape[0])[:, None] * np.hanning(array.shape[1])[None, :]
    spectrum = np.fft.fftshift(np.abs(np.fft.fft2(array * window)))

    # Log scale: raw magnitudes span too many orders of magnitude for a
    # single threshold to mean anything.
    spectrum = np.log1p(spectrum)

    height, width = spectrum.shape
    centre_y, centre_x = height // 2, width // 2

    # Mask out the low-frequency core. It is always the brightest part of any
    # spectrum and says nothing about periodicity.
    yy, xx = np.ogrid[:height, :width]
    ry = (yy - centre_y) / centre_y
    rx = (xx - centre_x) / centre_x
    radius = np.sqrt(ry ** 2 + rx ** 2)

    # Off-axis only: see MOIRE_AXIS_EXCLUDE. A document's own regular
    # structure lives on the axes; screen moire does not.
    off_axis = (np.abs(ry) > MOIRE_AXIS_EXCLUDE) & (np.abs(rx) > MOIRE_AXIS_EXCLUDE)
    outer = (radius > MOIRE_LOW_FREQ_EXCLUDE) & (radius < MOIRE_HIGH_FREQ_EXCLUDE) & off_axis

    values = spectrum[outer]
    if values.size == 0:
        return ScreenReplayResult(True, False, 0, 0.0, ["SCREEN_REPLAY_NOT_DETECTED"])

    mean = float(values.mean())
    deviation = float(values.std()) or 1e-6
    threshold = mean + MOIRE_PEAK_SIGMA * deviation

    peaks = spectrum > threshold
    peaks &= outer
    peak_count = int(peaks.sum())
    peak_strength = float((spectrum[peaks].mean() - mean) / deviation) if peak_count else 0.0

    likely = peak_count >= MOIRE_MIN_PEAKS
    reasons = ["SCREEN_REPLAY_SUSPECTED"] if likely else ["SCREEN_REPLAY_NOT_DETECTED"]

    return ScreenReplayResult(
        checked=True,
        likely_screen=likely,
        peak_count=peak_count,
        peak_strength=round(peak_strength, 2),
        reasons=reasons,
        detail={"sigma": MOIRE_PEAK_SIGMA, "min_peaks": MOIRE_MIN_PEAKS},
    )


# ---------------------------------------------------------------------------
# Copy-move
# ---------------------------------------------------------------------------

COPY_MOVE_BLOCK = 16
COPY_MOVE_STRIDE = 8
COPY_MOVE_MIN_PAIRS = 8       # matching pairs sharing one offset
COPY_MOVE_MIN_DISTANCE = 24   # ignore neighbours matching themselves
COPY_MOVE_TOLERANCE = 1.2     # how close two block signatures must be
COPY_MOVE_NEIGHBOURHOOD = 1   # sorted rows compared; see the validation note below


@dataclass
class CopyMoveResult:
    checked: bool
    detected: bool
    matched_pairs: int
    dominant_offset: tuple[int, int] | None
    reasons: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def detect_copy_move(image_bytes: bytes) -> CopyMoveResult:
    """
    Find a region of the image that has been duplicated elsewhere in it.

    This is the classic document forgery: cover an inconvenient value by
    pasting a patch of blank card over it, or duplicate a digit or a stamp.
    Unlike ELA it survives a re-save of the whole file, because the evidence
    is the duplication itself rather than a compression seam.

    Method: take overlapping blocks, reduce each to a small rotation-agnostic
    signature, sort so near-identical signatures land adjacent, then look for
    matched pairs that share the SAME positional offset. One offset shared by
    many pairs is what distinguishes a real copied region from the ordinary
    coincidence of two similar-looking patches.

    VALIDATION — READ BEFORE TRUSTING THIS
    --------------------------------------
    It does not currently work, and it is wired up so that it cannot accuse
    anyone while that remains true.

    Tested against a deliberately planted copy-move forgery (a patch of the
    card pasted over another part of it, generated by tools/make_forgeries.py)
    the counts were:

        genuine card fronts        2-3 matching pairs
        the planted forgery        2 matching pairs

    No separation at all. Widening the comparison window lifted every image
    to ~120 pairs together, genuine and forged alike, so no threshold exists
    that catches the forgery without also flagging honest documents. The
    only large scores came from the screen-replay specimen, where the
    simulated moire creates real periodic self-similarity — a confound, not
    a detection.

    The block signature (quadrant means plus spread) is too coarse to
    distinguish a pasted region from ordinary repetition in a rendered card.
    Making this real needs proper keypoint matching — SIFT/ORB descriptors
    with geometric verification — rather than a tighter threshold on a weak
    signature.

    So: the measurement is still returned in `detail` for anyone continuing
    the work, and the reason code is COPY_MOVE_NOT_VALIDATED, which claims
    nothing. Shipping it as a flag would have produced false accusations
    against honest documents, which is the one failure this project has
    consistently refused.
    """
    try:
        image = _load_grayscale(image_bytes)
    except Exception as exc:
        return CopyMoveResult(False, False, 0, None, ["COPY_MOVE_NOT_CHECKED"],
                              {"error": str(exc)[:200]})

    array = np.asarray(image, dtype=np.float32)
    height, width = array.shape

    # Copy-move analysis assumes natural image content, where a repeated
    # region is unusual. A QR code breaks that assumption completely: it is a
    # binary lattice engineered to repeat, so block matching finds dozens of
    # "duplicates" at a clean offset and reports a forgery that is not there.
    # Observed directly — a genuine Secure QR scored 46 matched pairs at a
    # uniform (0, 96) offset, which is the symbol's own structure.
    #
    # A near-bimodal histogram is the giveaway, so skip those rather than
    # accuse them.
    if _is_near_binary(array):
        return CopyMoveResult(
            checked=False, detected=False, matched_pairs=0, dominant_offset=None,
            reasons=["COPY_MOVE_NOT_CHECKED"],
            detail={"skipped": "image is near-binary (QR or line art); "
                               "block matching is not meaningful"},
        )

    signatures = []
    positions = []
    for y in range(0, height - COPY_MOVE_BLOCK, COPY_MOVE_STRIDE):
        for x in range(0, width - COPY_MOVE_BLOCK, COPY_MOVE_STRIDE):
            block = array[y:y + COPY_MOVE_BLOCK, x:x + COPY_MOVE_BLOCK]
            # Skip near-flat blocks: blank regions match each other everywhere
            # and would swamp the result with meaningless pairs.
            if block.std() < 4.0:
                continue
            signatures.append(_block_signature(block))
            positions.append((y, x))

    if len(signatures) < COPY_MOVE_MIN_PAIRS * 2:
        return CopyMoveResult(True, False, 0, None, ["COPY_MOVE_NOT_DETECTED"],
                              {"blocks_considered": len(signatures)})

    matrix = np.asarray(signatures, dtype=np.float32)
    positions_array = np.asarray(positions)

    # Lexicographic sort brings similar signatures next to one another, which
    # turns an O(n^2) all-pairs comparison into a scan of adjacent rows.
    order = np.lexsort(matrix.T[::-1])
    matrix = matrix[order]
    positions_array = positions_array[order]

    # Compare each row against the next few, not only its immediate
    # neighbour. Sorting brings similar signatures close together but does
    # not guarantee an exact pair lands adjacent — with a single-step
    # comparison a real pasted region scored only 2 matches out of 540
    # blocks, because its duplicates sorted two or three rows apart.
    offsets: dict[tuple[int, int], int] = {}
    for index in range(len(matrix) - 1):
        for step in range(1, COPY_MOVE_NEIGHBOURHOOD + 1):
            other = index + step
            if other >= len(matrix):
                break
            distance = float(np.abs(matrix[index] - matrix[other]).sum())
            if distance > COPY_MOVE_TOLERANCE:
                continue
            y1, x1 = positions_array[index]
            y2, x2 = positions_array[other]
            shift = (int(y2 - y1), int(x2 - x1))
            if abs(shift[0]) + abs(shift[1]) < COPY_MOVE_MIN_DISTANCE:
                continue
            # Normalise direction so A->B and B->A count as the same offset.
            if shift[0] < 0 or (shift[0] == 0 and shift[1] < 0):
                shift = (-shift[0], -shift[1])
            offsets[shift] = offsets.get(shift, 0) + 1

    if not offsets:
        return CopyMoveResult(True, False, 0, None, ["COPY_MOVE_NOT_DETECTED"],
                              {"blocks_considered": len(signatures)})

    dominant, count = max(offsets.items(), key=lambda item: item[1])
    detected = count >= COPY_MOVE_MIN_PAIRS

    return CopyMoveResult(
        checked=True,
        detected=detected,
        matched_pairs=int(count),
        dominant_offset=dominant if detected else None,
        # NOT an accusation. See VALIDATION in the docstring: this detector
        # showed no separation between a planted copy-move forgery and a
        # genuine card, so it reports a measurement and nothing more.
        reasons=["COPY_MOVE_NOT_VALIDATED"],
        detail={"blocks_considered": len(signatures),
                "min_pairs": COPY_MOVE_MIN_PAIRS},
    )


# ---------------------------------------------------------------------------
# Noise inconsistency
# ---------------------------------------------------------------------------

NOISE_TILE = 64
NOISE_OUTLIER_SIGMA = 3.0
NOISE_MIN_OUTLIER_FRACTION = 0.06
NOISE_EDGE_LIMIT = 46.0       # tile contrast above which content, not noise, dominates


@dataclass
class NoiseResult:
    checked: bool
    inconsistent: bool
    outlier_fraction: float
    tiles: int
    reasons: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def detect_noise_inconsistency(image_bytes: bytes) -> NoiseResult:
    """
    Compare sensor-noise level across the image.

    One camera, one exposure, one noise floor. Splice in a region from another
    photograph — or from a synthetic render, which typically has almost no
    sensor noise at all — and that region's high-frequency residual no longer
    matches its surroundings.

    Method: a Laplacian-style high-pass residual per tile, then flag tiles
    whose residual energy is a long way from the image's own median. Using
    the median rather than the mean matters, because a large spliced region
    would drag a mean toward itself and hide the very thing being looked for.

    Limits: heavy global denoising or a hard re-compression flattens noise
    everywhere and erases the signal. Genuinely flat regions — a blank
    margin, an overexposed patch — read as low noise without anything being
    wrong, which is part of why the outlier fraction has to clear a floor
    before this reports.
    """
    try:
        image = _load_grayscale(image_bytes)
    except Exception as exc:
        return NoiseResult(False, False, 0.0, 0, ["NOISE_NOT_CHECKED"],
                           {"error": str(exc)[:200]})

    array = np.asarray(image, dtype=np.float32)

    # High-pass residual: subtract a local mean, leaving mostly noise plus
    # edges. A 3x3 box blur via cumulative sums keeps this dependency-free.
    blurred = _box_blur(array, 3)
    residual = array - blurred

    height, width = residual.shape
    energies = []
    skipped_edges = 0
    for y in range(0, height - NOISE_TILE + 1, NOISE_TILE):
        for x in range(0, width - NOISE_TILE + 1, NOISE_TILE):
            tile = residual[y:y + NOISE_TILE, x:x + NOISE_TILE]

            # Skip tiles dominated by edges. A high-pass residual over a
            # document is mostly TYPE, not sensor noise: printed text put the
            # median tile energy at 13.1 on a rendered card, which drowned a
            # spliced-in photograph completely. Sensor noise is the small,
            # dense component, so estimate it where there is no type — the
            # robust median-absolute-deviation of the tile, which ignores the
            # few large excursions an edge produces.
            source_tile = array[y:y + NOISE_TILE, x:x + NOISE_TILE]
            if float(source_tile.std()) > NOISE_EDGE_LIMIT:
                skipped_edges += 1
                continue

            deviation = float(np.median(np.abs(tile - np.median(tile))))
            energies.append(deviation * 1.4826)

    if len(energies) < 6:
        return NoiseResult(True, False, 0.0, len(energies),
                           ["NOISE_NOT_CHECKED"], {"reason": "image too small to tile"})

    values = np.asarray(energies)
    median = float(np.median(values))
    # Median absolute deviation: robust to a large spliced area, where a plain
    # standard deviation would be pulled toward the splice.
    mad = float(np.median(np.abs(values - median))) or 1e-6
    scaled = np.abs(values - median) / (1.4826 * mad)

    outlier_fraction = float((scaled > NOISE_OUTLIER_SIGMA).mean())
    inconsistent = outlier_fraction >= NOISE_MIN_OUTLIER_FRACTION

    return NoiseResult(
        checked=True,
        inconsistent=inconsistent,
        outlier_fraction=round(outlier_fraction, 4),
        tiles=len(energies),
        reasons=["NOISE_INCONSISTENT"] if inconsistent else ["NOISE_CONSISTENT"],
        detail={"median_noise": round(median, 3),
                "edge_tiles_skipped": skipped_edges,
                "threshold_fraction": NOISE_MIN_OUTLIER_FRACTION},
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

EDITOR_SIGNATURES = (
    "photoshop", "gimp", "lightroom", "paint", "snapseed", "picsart",
    "canva", "imagemagick", "pillow", "affinity", "pixlr", "inkscape",
)


@dataclass
class MetadataResult:
    checked: bool
    editor: str | None
    has_camera_tags: bool
    reasons: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def inspect_metadata(image_bytes: bytes) -> MetadataResult:
    """
    Read what the file says about its own history.

    Cheap, and occasionally decisive: an image whose EXIF still names an
    image editor was, on its own admission, opened and re-saved by one.

    This is evidence about the FILE, not the document. A scanned document
    legitimately passes through software, and stripped metadata is the norm
    for anything that has been through a messaging app — so absence proves
    nothing and is never reported as suspicious. Only a positive editor
    signature is worth surfacing, and even then only as advisory.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        exif = image.getexif()
    except Exception as exc:
        return MetadataResult(False, None, False, ["METADATA_NOT_CHECKED"],
                              {"error": str(exc)[:200]})

    if not exif:
        # Genuinely common and not suspicious on its own.
        return MetadataResult(True, None, False, ["METADATA_ABSENT"], {})

    software = str(exif.get(305, "") or "").strip()
    make = str(exif.get(271, "") or "").strip()
    model = str(exif.get(272, "") or "").strip()

    lowered = software.lower()
    editor = next((name for name in EDITOR_SIGNATURES if name in lowered), None)

    reasons = []
    if editor:
        reasons.append("METADATA_EDITOR_PRESENT")
    else:
        reasons.append("METADATA_NO_EDITOR")

    return MetadataResult(
        checked=True,
        editor=editor,
        has_camera_tags=bool(make or model),
        reasons=reasons,
        detail={"software": software[:80], "camera": f"{make} {model}".strip()[:80]},
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_grayscale(image_bytes: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(image_bytes)).convert("L")
    if max(image.size) > WORKING_EDGE:
        scale = WORKING_EDGE / max(image.size)
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )
    return image


def _is_near_binary(array: np.ndarray, extreme_fraction: float = 0.90) -> bool:
    """
    Is this essentially a two-tone image — a QR, a barcode, line art?

    Measured as the share of pixels in the darkest or lightest fifth of the
    range. A photograph spreads across the middle; a QR does not.

    Measured on the specimens available:

        real photographs          0.02 - 0.11
        rendered card fronts      0.83 - 0.85
        a genuine Secure QR       0.86
        the QR that false-positived  1.00

    0.90 separates them. Note the honest caveat: the rendered demo cards sit
    much closer to the QR range than a photographed document would, because
    they are drawn on flat backgrounds rather than captured. This guard is
    therefore calibrated on limited data and is worth revisiting against real
    photographs of real documents.
    """
    dark = array < 51
    light = array > 204
    return float((dark | light).mean()) >= extreme_fraction


def _block_signature(block: np.ndarray) -> np.ndarray:
    """
    Reduce a block to a short, comparable signature.

    Quadrant means plus the block's own spread: enough to tell genuinely
    different content apart, coarse enough that a re-saved copy of the same
    region still matches it. Mean-centred so a brightness shift alone does
    not break the match.
    """
    half = block.shape[0] // 2
    quadrants = [
        block[:half, :half].mean(), block[:half, half:].mean(),
        block[half:, :half].mean(), block[half:, half:].mean(),
    ]
    centred = np.asarray(quadrants, dtype=np.float32) - float(block.mean())
    return np.round(np.append(centred, block.std()), 1)


def _box_blur(array: np.ndarray, radius: int) -> np.ndarray:
    """Separable box blur via cumulative sums; avoids a scipy dependency."""
    padded = np.pad(array, radius, mode="edge")
    cumulative = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    cumulative = np.pad(cumulative, ((1, 0), (1, 0)), mode="constant")

    size = 2 * radius + 1
    height, width = array.shape
    total = (
        cumulative[size:size + height, size:size + width]
        - cumulative[0:height, size:size + width]
        - cumulative[size:size + height, 0:width]
        + cumulative[0:height, 0:width]
    )
    return total / (size * size)


def analyse_all(image_bytes: bytes) -> dict:
    """
    Run every detector and collect their reason codes.

    Returned as one bundle so callers add a single block of advisory signals
    rather than wiring four detectors into every endpoint.
    """
    screen = detect_screen_replay(image_bytes)
    copy_move = detect_copy_move(image_bytes)
    noise = detect_noise_inconsistency(image_bytes)
    metadata = inspect_metadata(image_bytes)

    codes: list[str] = []
    for result in (screen, copy_move, noise, metadata):
        codes.extend(result.reasons)

    return {
        "reasons": codes,
        "screen_replay": {
            "checked": screen.checked,
            "likely_screen": screen.likely_screen,
            "peak_count": screen.peak_count,
            "peak_strength": screen.peak_strength,
        },
        "copy_move": {
            "checked": copy_move.checked,
            "detected": copy_move.detected,
            "matched_pairs": copy_move.matched_pairs,
            "dominant_offset": copy_move.dominant_offset,
        },
        "noise": {
            "checked": noise.checked,
            "inconsistent": noise.inconsistent,
            "outlier_fraction": noise.outlier_fraction,
            "tiles": noise.tiles,
        },
        "metadata": {
            "checked": metadata.checked,
            "editor": metadata.editor,
            "has_camera_tags": metadata.has_camera_tags,
        },
    }


# ---------------------------------------------------------------------------
# Visual maps
# ---------------------------------------------------------------------------
#
# ELA can produce a heatmap, but only for JPEGs that still carry an editing
# history — it declines every PNG, which is most of what this system is handed,
# so in practice the UI had nothing to show. These two maps are built from the
# measurements the detectors already compute, so they work on any format and
# every pixel in them corresponds to something real.

def _to_png_base64(array: np.ndarray) -> str:
    import base64

    buffer = io.BytesIO()
    Image.fromarray(array.astype("uint8")).save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _ramp(normalised: np.ndarray) -> np.ndarray:
    """
    Map 0..1 onto near-black -> saffron -> white.

    A single-hue ramp, not a rainbow. Rainbow maps invent visual boundaries
    where the data has none — a jump from green to yellow reads as a step
    change that is not in the numbers — and they are unreadable to a large
    share of colour-blind viewers. Brightness alone carries the ordering here.
    """
    value = np.clip(normalised, 0.0, 1.0)
    red = np.clip(value * 2.6, 0, 1)
    green = np.clip(value * 1.7 - 0.12, 0, 1)
    blue = np.clip(value * 1.5 - 0.62, 0, 1)
    stack = np.stack([red, green, blue], axis=-1) * 255.0
    # Lift the floor so the map reads as a surface rather than a black hole.
    return np.clip(stack + 10, 0, 255)


def render_noise_map(image_bytes: bytes, tile: int = 16) -> str | None:
    """
    Per-tile sensor-noise energy, as an image.

    This is the same measurement `detect_noise_inconsistency` scores, drawn
    instead of reduced to a number. A spliced-in region shows as a patch whose
    brightness differs from its surroundings, which is exactly the thing the
    detector is reacting to — so an operator can see whether the finding is
    real or is just an edge.
    """
    try:
        image = _load_grayscale(image_bytes)
    except Exception:
        return None

    array = np.asarray(image, dtype=np.float32)
    residual = array - _box_blur(array, 3)

    height, width = residual.shape
    rows, columns = height // tile, width // tile
    if rows < 2 or columns < 2:
        return None

    grid = np.zeros((rows, columns), dtype=np.float32)
    for row in range(rows):
        for column in range(columns):
            patch = residual[row * tile:(row + 1) * tile, column * tile:(column + 1) * tile]
            # Robust spread, so one hard edge in a tile does not dominate it.
            grid[row, column] = float(np.median(np.abs(patch - np.median(patch))))

    # Percentile normalisation: a single extreme tile would otherwise flatten
    # everything else to black.
    high = float(np.percentile(grid, 97)) or 1e-6
    normalised = np.clip(grid / high, 0, 1)

    coloured = _ramp(normalised)
    return _to_png_base64(
        np.asarray(
            Image.fromarray(coloured.astype("uint8")).resize(
                (columns * tile, rows * tile), Image.NEAREST
            )
        )
    )


def render_spectrum(image_bytes: bytes) -> str | None:
    """
    The frequency spectrum the screen-replay check actually reads.

    Worth drawing because it is legible without training: a normal photograph
    fades smoothly outward from the centre, while a photograph of a screen
    carries bright isolated dots away from the middle — the moire peaks. When
    the detector reports SCREEN_REPLAY_SUSPECTED, this is the evidence, and
    anyone can see whether it is there.
    """
    try:
        image = _load_grayscale(image_bytes)
    except Exception:
        return None

    array = np.asarray(image, dtype=np.float32) / 255.0
    window = np.hanning(array.shape[0])[:, None] * np.hanning(array.shape[1])[None, :]
    spectrum = np.log1p(np.fft.fftshift(np.abs(np.fft.fft2(array * window))))

    low = float(np.percentile(spectrum, 55))
    high = float(np.percentile(spectrum, 99.9))
    normalised = np.clip((spectrum - low) / max(high - low, 1e-6), 0, 1)

    # Downscale before encoding. A full-resolution spectrum encodes to ~170 KB
    # of noise-like pixels, which is a lot to push through a JSON response for
    # something a viewer reads at a glance. Peaks survive the reduction because
    # they are bright and isolated.
    picture = Image.fromarray(_ramp(normalised).astype("uint8"))
    picture.thumbnail((320, 320), Image.LANCZOS)
    return _to_png_base64(np.asarray(picture))


def render_maps(image_bytes: bytes) -> dict:
    """Both maps, base64 PNG, ready to drop straight into an <img src>."""
    return {
        "noise_map_png_base64": render_noise_map(image_bytes),
        "spectrum_png_base64": render_spectrum(image_bytes),
    }

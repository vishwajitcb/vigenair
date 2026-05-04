"""Variant segment normalization: dedupe overlapping segments, reorder per
structure, recompute true duration.

Used by both the variant-generation path (segments.py validate_variants) and
the render path (render.py _transform_variants_for_combiner) so the same
correctness invariant holds at gen time and at render time.

Idempotent: running normalize_variant_segments on already-normalized output
returns the same output (modulo logging).
"""

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_STRUCTURE = "chronological"
VALID_STRUCTURES = {"chronological", "cold_open_flashback"}


def normalize_variant_segments(
    segment_ids: Sequence,
    segments_by_id: Dict[str, Dict[str, Any]],
    hook_scene: Optional[int],
    structure: Optional[str],
    *,
    variant_label: str,
) -> Tuple[List[str], float, Dict[str, Any]]:
    """Run dedupe -> reorder -> duration pipeline.

    Args:
        segment_ids: Gemini's emitted segment IDs (list of int or str).
        segments_by_id: {id_str: {start_s, end_s, duration_s, ...}} from data.json.
        hook_scene: 1-indexed scene number Gemini designated as the hook (or None).
        structure: "chronological" | "cold_open_flashback" | None.
        variant_label: human-readable label for log correlation.

    Returns:
        (ordered_segment_id_strs, true_duration_s, debug_info).
    """
    structure_requested = structure
    if structure not in VALID_STRUCTURES:
        if structure is not None:
            logger.warning(
                f"VARIANT_NORM_INVALID_STRUCTURE label={variant_label!r} "
                f"got={structure!r}, defaulting to {DEFAULT_STRUCTURE}"
            )
        structure = DEFAULT_STRUCTURE

    # Stringify IDs and split into known / unknown.
    str_ids = [str(s) for s in segment_ids]
    known: List[str] = []
    dropped_unknown: List[str] = []
    for sid in str_ids:
        if sid in segments_by_id:
            known.append(sid)
        else:
            dropped_unknown.append(sid)
    if dropped_unknown:
        logger.warning(
            f"VARIANT_NORM_UNKNOWN_IDS label={variant_label!r} "
            f"ids={dropped_unknown}"
        )

    input_summed_duration = sum(
        float(segments_by_id.get(sid, {}).get("duration_s", 0.0)) for sid in known
    )

    # Dedupe.
    deduped, dropped_overlap = _dedupe_overlapping(known, segments_by_id)
    for kept_id, dropped_id, reason in dropped_overlap:
        logger.info(
            f"VARIANT_NORM_DROP label={variant_label!r} "
            f"kept={kept_id} dropped={dropped_id} reason={reason!r}"
        )

    # Reorder.
    if structure == "cold_open_flashback":
        ordered = _reorder_cold_open_flashback(
            deduped, segments_by_id, hook_scene, variant_label=variant_label
        )
    else:
        ordered = _reorder_chronological(deduped, segments_by_id)

    output_true_duration = _compute_true_duration(ordered, segments_by_id)

    shrink_pct = 0.0
    if input_summed_duration > 0:
        shrink_pct = (
            1.0 - (output_true_duration / input_summed_duration)
        ) * 100.0

    debug = {
        "input_count": len(str_ids),
        "input_ids": str_ids,
        "dropped_overlap": dropped_overlap,
        "dropped_unknown": dropped_unknown,
        "structure_requested": structure_requested,
        "structure_used": structure,
        "reorder_applied": True,
        "output_count": len(ordered),
        "output_ids": ordered,
        "input_summed_duration": round(input_summed_duration, 3),
        "output_true_duration": round(output_true_duration, 3),
        "shrink_pct": round(shrink_pct, 1),
    }

    logger.info(
        f"VARIANT_NORM label={variant_label!r} "
        f"input={len(str_ids)} unknown={len(dropped_unknown)} "
        f"overlap_dropped={len(dropped_overlap)} "
        f"structure={structure} "
        f"output={len(ordered)} "
        f"dur_in={input_summed_duration:.1f} "
        f"dur_out={output_true_duration:.1f} "
        f"shrink={shrink_pct:.0f}%"
    )

    if shrink_pct >= 50.0 and len(str_ids) > 0:
        logger.warning(
            f"VARIANT_NORM_SHRINK label={variant_label!r} "
            f"shrink_pct={shrink_pct:.1f}% "
            f"(input={input_summed_duration:.1f}s -> output={output_true_duration:.1f}s) — "
            f"likely heavy overlap in source data.json"
        )
    if len(ordered) == 0 and len(str_ids) > 0:
        logger.warning(
            f"VARIANT_NORM_EMPTY label={variant_label!r} "
            f"all {len(str_ids)} segments dropped (overlap/unknown)"
        )

    return ordered, output_true_duration, debug


def _dedupe_overlapping(
    seg_ids: List[str],
    segments_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    """Drop segments whose [start_s, end_s] overlaps with an already-kept segment.

    Rule: ANY time overlap = drop. When two overlap, keep the longer-duration one;
    on tie keep the earlier-listed (preserves Gemini's hook ordering).

    Comparison is symmetric: we walk the input order, but when a candidate
    overlaps a previously-kept segment, we may swap if the candidate is longer.
    """
    kept: List[str] = []
    dropped: List[Tuple[str, str, str]] = []

    for cand_id in seg_ids:
        cand = segments_by_id.get(cand_id, {})
        cand_start = float(cand.get("start_s", 0.0))
        cand_end = float(cand.get("end_s", 0.0))
        cand_dur = max(0.0, cand_end - cand_start)
        if cand_dur <= 0:
            # Zero-duration or malformed segment — drop with reason.
            dropped.append((cand_id, cand_id, "zero_or_negative_duration"))
            continue

        overlap_with_idx = -1
        for i, kept_id in enumerate(kept):
            kept_seg = segments_by_id[kept_id]
            kept_start = float(kept_seg.get("start_s", 0.0))
            kept_end = float(kept_seg.get("end_s", 0.0))
            if _intervals_overlap(cand_start, cand_end, kept_start, kept_end):
                overlap_with_idx = i
                break

        if overlap_with_idx == -1:
            kept.append(cand_id)
            continue

        # Candidate overlaps an already-kept segment. Decide which to keep.
        kept_id = kept[overlap_with_idx]
        kept_seg = segments_by_id[kept_id]
        kept_dur = float(kept_seg.get("end_s", 0.0)) - float(
            kept_seg.get("start_s", 0.0)
        )
        reason = (
            f"overlap [{cand_start:.3f},{cand_end:.3f}] vs "
            f"[{kept_seg.get('start_s', 0):.3f},{kept_seg.get('end_s', 0):.3f}]"
        )
        if cand_dur > kept_dur:
            # Candidate is longer — swap.
            kept[overlap_with_idx] = cand_id
            dropped.append((cand_id, kept_id, reason + f" (swap: {kept_dur:.2f}s -> {cand_dur:.2f}s)"))
        else:
            # Keep existing.
            dropped.append((kept_id, cand_id, reason))

    return kept, dropped


def _intervals_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    """True if [a_start, a_end] and [b_start, b_end] share any time.
    Touching boundaries (a_end == b_start) does NOT count as overlap."""
    return a_start < b_end and b_start < a_end


def _reorder_chronological(
    seg_ids: List[str],
    segments_by_id: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Stable sort by start_s ascending."""
    return sorted(
        seg_ids,
        key=lambda sid: float(segments_by_id.get(sid, {}).get("start_s", 0.0)),
    )


def _reorder_cold_open_flashback(
    seg_ids: List[str],
    segments_by_id: Dict[str, Dict[str, Any]],
    hook_scene: Optional[int],
    *,
    variant_label: str,
) -> List[str]:
    """Hook scene first, then earlier-time scenes ('flashback'), then later-time
    scenes ('continuation'), each chronologically.

    If hook_scene is None or not present in seg_ids, fall back to chronological.
    """
    hook_id = str(hook_scene) if hook_scene is not None else None
    if not hook_id or hook_id not in seg_ids:
        logger.warning(
            f"VARIANT_NORM_HOOK_MISSING label={variant_label!r} "
            f"hook_scene={hook_scene!r} not in segment list, "
            f"falling back to chronological"
        )
        return _reorder_chronological(seg_ids, segments_by_id)

    hook_start = float(segments_by_id[hook_id].get("start_s", 0.0))
    before: List[str] = []
    after: List[str] = []
    for sid in seg_ids:
        if sid == hook_id:
            continue
        sid_start = float(segments_by_id.get(sid, {}).get("start_s", 0.0))
        if sid_start < hook_start:
            before.append(sid)
        else:
            after.append(sid)

    before_sorted = _reorder_chronological(before, segments_by_id)
    after_sorted = _reorder_chronological(after, segments_by_id)

    return [hook_id] + before_sorted + after_sorted


def _compute_true_duration(
    seg_ids: List[str],
    segments_by_id: Dict[str, Dict[str, Any]],
) -> float:
    """Sum (end_s - start_s) for each segment. Assumes deduped (no overlap)."""
    total = 0.0
    for sid in seg_ids:
        seg = segments_by_id.get(sid, {})
        total += max(0.0, float(seg.get("end_s", 0.0)) - float(seg.get("start_s", 0.0)))
    return total

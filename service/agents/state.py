"""Graph state definitions for the variant-generation pipeline.

The pipeline carries one shared state dict from node to node. Per-variant work
lives in `state["variants"]` as a list of `VariantInProgress` dicts. A
node may drop a variant by omitting it from the list it returns; surviving
variants flow downstream. Per-pipeline failures (e.g. HookScout) are recorded
on the top-level state and the pipeline still runs.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VariantInProgress(TypedDict, total=False):
    """A single variant flowing through the graph.

    Fields are added incrementally:
      - Builder writes: title, angle, hook_scene, structure, segments,
        cliffhanger_scenes, description, reasoning, estimated_duration, score
      - Auditor writes: audited (bool), audit_insertions (list[int])
      - Normalizer writes: actual_duration, structure (validated)
      - Validator may drop the variant if schema/uniqueness checks fail.
    Also carries `assigned_hook` (the Hook dict from Pass 1) for traceability.
    """

    assigned_hook: Optional[Dict[str, Any]]

    # ---- HookAnalyst output (per-variant LLM) ----
    dramatic_question: str
    emotional_beat: str
    who_must_we_see: List[str]
    what_must_be_at_stake: str

    # ---- StoryScout / CliffhangerScout candidates (over-generated) ----
    story_candidates: List[Dict[str, Any]]      # [{"scene": int, "escalates_because": str}]
    cliffhanger_candidates: List[Dict[str, Any]]  # [{"scene": int, "leaves_unresolved_because": str}]

    # ---- CutEditor output (the final variant body) ----
    title: str
    angle: str
    hook_scene: Optional[int]
    structure: str
    segments: List[Any]
    cliffhanger_scenes: List[int]
    description: str
    reasoning: str
    estimated_duration: float
    actual_duration: float
    score: float

    # ---- AdShapeJudge output ----
    judge_verdict: str          # "ad_shape_ok" | "off_topic" | "show_segment_feel" | "weak_open" | "weak_close"
    judge_rationale: str
    judge_retried: bool

    # ---- Auditor output (existing) ----
    audited: bool
    audit_insertions: List[int]


class PipelineState(TypedDict, total=False):
    """Shared state passed between graph nodes."""

    # ---- Inputs (set once before graph.invoke) ----
    folder: str
    request_params: Dict[str, Any]      # raw request fields used by builder/auditor prompts
    segments_text: str                  # rendered Segment N (Xs): description block
    segments_by_id: Dict[str, Dict[str, Any]]  # 1-indexed-str -> segment dict
    eligible_indices: List[int]
    num_variants: int
    target_duration: float
    expected_duration_range: str
    max_allowed_duration: float
    video_language: str
    score_max: int

    # ---- Filled by HookScout ----
    hook_inventory: Optional[Dict[str, Any]]   # parsed Pass-1 JSON, or None on failure
    hook_inventory_block: str                  # formatted prompt-ready block, "" if no inventory

    # ---- Filled by HookSelector ----
    assignment: List[Dict[str, Any]]           # list of Hook dicts; one per requested variant

    # ---- Built incrementally by VariantBuilder/Auditor/Normalizer/Validator ----
    variants: List[VariantInProgress]

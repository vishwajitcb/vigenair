"""Pydantic schemas for parsing Gemini responses.

Each schema mirrors the prompt-emitted JSON shape from variant_prompts.py.
Validation is intentionally permissive (Optional + default fallbacks) because
prompts emit a superset of what we strictly need; we want to fail-loud only
on the fields downstream nodes actually depend on.
"""

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


# ---- Pass 1: Hook Inventory ----

class Hook(BaseModel):
    id: Optional[str] = None
    scene: int
    hook_type: Optional[str] = None
    emotion: Optional[str] = None
    dynamic: Optional[str] = None
    character_ids: List[str] = Field(default_factory=list)
    label: Optional[str] = None
    strength: Optional[str] = None
    open_loop_potential: Optional[str] = None
    suggested_story_scenes: List[int] = Field(default_factory=list)
    suggested_cliffhanger_scenes: List[int] = Field(default_factory=list)
    rationale: Optional[str] = None


class Character(BaseModel):
    id: str
    label: Optional[str] = None
    scenes: List[int] = Field(default_factory=list)
    role: Optional[str] = None


class HookInventory(BaseModel):
    show_summary: Optional[str] = ""
    characters: List[Character] = Field(default_factory=list)
    dynamics_present: List[str] = Field(default_factory=list)
    hooks: List[Hook] = Field(default_factory=list)


# ---- Pass 2: Variant Construction (one variant per LLM call) ----

class BuiltVariant(BaseModel):
    title: str
    angle: Optional[str] = None
    hook_scene: Optional[int] = None
    structure: Optional[str] = None
    segments: List[Any] = Field(default_factory=list)
    cliffhanger_scenes: List[int] = Field(default_factory=list)
    description: Optional[str] = None
    reasoning: Optional[str] = None
    estimated_duration: Optional[float] = None
    score: Optional[float] = None


class BuiltVariantBatch(BaseModel):
    """The Pass-2 prompt template emits a {"variants": [...]} envelope even
    when num_variants=1. We accept both the envelope and a bare object."""

    variants: List[BuiltVariant] = Field(default_factory=list)


# ---- Pass 3: Audit ----

class AuditResult(BaseModel):
    insertions: List[int] = Field(default_factory=list)
    rationale: Optional[str] = None


# ---- v2 per-variant chain (HookAnalyst → StoryScout → CliffhangerScout → CutEditor → AdShapeJudge) ----

class HookAnalysis(BaseModel):
    """HookAnalyst output. Answers 'what does this hook PROMISE the viewer?'

    All fields except dramatic_question are made permissive — the model
    occasionally drops what_must_be_at_stake or emotional_beat, and dropping
    the variant for that is too strict. The downstream agents handle
    empty-string values cleanly.
    """
    dramatic_question: str
    emotional_beat: str = ""
    who_must_we_see: List[str] = Field(default_factory=list)
    what_must_be_at_stake: str = ""


class StoryCandidate(BaseModel):
    scene: int
    escalates_because: str


class StoryScoutResult(BaseModel):
    """StoryScout over-generates 5–8 candidate story scenes with per-scene
    justification. CutEditor decides which actually ship."""
    candidates: List[StoryCandidate] = Field(default_factory=list)


class CliffhangerCandidate(BaseModel):
    scene: int
    leaves_unresolved_because: str


class CliffhangerScoutResult(BaseModel):
    """CliffhangerScout over-generates 2–3 candidate closing scenes."""
    candidates: List[CliffhangerCandidate] = Field(default_factory=list)


class CutEditorResult(BaseModel):
    """Final variant body. Same shape as the legacy BuiltVariant — keeps
    downstream Auditor/Normalizer/Validator unchanged."""
    title: str
    angle: Optional[str] = None
    hook_scene: Optional[int] = None
    structure: Optional[str] = None
    segments: List[Any] = Field(default_factory=list)
    cliffhanger_scenes: List[int] = Field(default_factory=list)
    description: Optional[str] = None
    reasoning: Optional[str] = None
    estimated_duration: Optional[float] = None
    score: Optional[float] = None


JudgeVerdictLiteral = Literal[
    "ad_shape_ok",
    "off_topic",
    "show_segment_feel",
    "weak_open",
    "weak_close",
]


class JudgeVerdict(BaseModel):
    """AdShapeJudge categorical verdict. Non-ok triggers ONE CutEditor retry."""
    verdict: JudgeVerdictLiteral
    rationale: str

"""Pydantic models for MongoDB documents."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job status enumeration."""
    PROCESSING = "processing"
    SEGMENTS_READY = "segments_ready"
    VARIANTS_GENERATED = "variants_generated"
    RENDERING = "rendering"
    COMPLETE = "complete"
    ERROR = "error"


class JobStage(str, Enum):
    """Processing stage enumeration."""
    UPLOADING = "uploading"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    CREATING_SEGMENTS = "creating_segments"
    DONE = "done"
    # Render stages
    RENDER_PREPARING = "render_preparing"
    RENDER_CROPPING = "render_cropping"
    RENDER_ENCODING = "render_encoding"
    RENDER_UPLOADING = "render_uploading"
    RENDER_FINALIZING = "render_finalizing"


class Segment(BaseModel):
    """Video segment model."""
    id: str
    startTime: float = 0.0
    endTime: float = 0.0
    duration: float = 0.0
    description: Optional[str] = None
    keywords: List[str] = []
    transcript: Optional[str] = None


class Variant(BaseModel):
    """Generated variant model."""
    id: int
    title: str
    description: Optional[str] = None
    score: float = 0.0
    reasoning: Optional[str] = None
    segments: List[str] = []  # Segment IDs
    duration: float = 0.0
    userModified: bool = False


class GenerationSettings(BaseModel):
    """Variant generation settings."""
    promptOption: str = "default"
    customPrompt: str = ""
    targetDuration: float = 30.0
    shortenVideo: bool = True
    businessObjective: Optional[str] = None


class RenderSettings(BaseModel):
    """Render settings for a variant."""
    formats: List[str] = ["16:9"]
    audioMode: str = "segment"
    overlayType: str = "variant_start"
    fadeOut: bool = False
    blankingFill: bool = False
    generateAssets: bool = True


class RenderQueueItem(BaseModel):
    """Item in render queue."""
    variantId: int
    segments: List[str] = []
    settings: RenderSettings = Field(default_factory=RenderSettings)


class RenderedFormat(BaseModel):
    """Rendered video format with URL and approval status."""
    url: Optional[str] = None
    approved: bool = False


class RenderedVariant(BaseModel):
    """Rendered variant with formats and assets."""
    variantId: int
    formats: Dict[str, RenderedFormat] = {}
    images: List[str] = []
    texts: List[Dict[str, Any]] = []


class Render(BaseModel):
    """Completed render job."""
    id: str
    name: str
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    status: str = "processing"
    variants: List[RenderedVariant] = []


class UIState(BaseModel):
    """UI state to persist."""
    activeTab: str = "segments"
    previewAspectRatio: str = "16:9"
    selectedSegments: List[str] = []


class Job(BaseModel):
    """Main Job document model."""
    # Identity
    folder: str  # S3 folder name (unique identifier)
    name: str  # Display name parsed from folder
    userId: str = "default"  # For future auth

    # Timestamps
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

    # Status
    status: JobStatus = JobStatus.PROCESSING
    stage: JobStage = JobStage.UPLOADING
    error: Optional[str] = None
    progress: int = 0

    # S3 paths (not presigned URLs - generate on request)
    inputVideoKey: Optional[str] = None
    thumbnailKey: Optional[str] = None

    # Analysis results
    transcript: Optional[Dict[str, Any]] = None
    analysisComplete: bool = False

    # Segments
    segments: List[Segment] = []
    segmentOrder: List[str] = []

    # Variant generation
    generationSettings: GenerationSettings = Field(default_factory=GenerationSettings)
    variants: List[Variant] = []
    selectedVariantIndex: int = 0

    # Rendering
    renderQueue: List[RenderQueueItem] = []
    renders: List[Render] = []

    # UI state
    ui: UIState = Field(default_factory=UIState)

    class Config:
        use_enum_values = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        data = self.model_dump()
        # Convert datetime objects to ISO strings for JSON serialization
        if isinstance(data.get("createdAt"), datetime):
            data["createdAt"] = data["createdAt"].isoformat()
        if isinstance(data.get("updatedAt"), datetime):
            data["updatedAt"] = data["updatedAt"].isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create Job from MongoDB document."""
        # Handle _id field
        if "_id" in data:
            del data["_id"]
        return cls(**data)


class JobCreate(BaseModel):
    """Model for creating a new job."""
    folder: str
    name: str
    userId: str = "default"
    inputVideoKey: Optional[str] = None


class JobUpdate(BaseModel):
    """Model for updating a job."""
    status: Optional[JobStatus] = None
    stage: Optional[JobStage] = None
    error: Optional[str] = None
    progress: Optional[int] = None
    segments: Optional[List[Segment]] = None
    segmentOrder: Optional[List[str]] = None
    variants: Optional[List[Variant]] = None
    selectedVariantIndex: Optional[int] = None
    generationSettings: Optional[GenerationSettings] = None
    renderQueue: Optional[List[RenderQueueItem]] = None
    renders: Optional[List[Render]] = None
    ui: Optional[UIState] = None
    transcript: Optional[Dict[str, Any]] = None
    analysisComplete: Optional[bool] = None
    thumbnailKey: Optional[str] = None


class JobListItem(BaseModel):
    """Simplified job item for list views."""
    folder: str
    name: str
    status: JobStatus
    stage: JobStage
    createdAt: datetime
    error: Optional[str] = None
    thumbnailUrl: Optional[str] = None  # Presigned URL
    variantCount: int = 0
    renderCount: int = 0

    class Config:
        use_enum_values = True

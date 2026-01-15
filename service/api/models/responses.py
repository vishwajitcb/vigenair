# Copyright 2024 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pydantic response models for ViGenAiR API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check response."""
    status: str


class UploadResponse(BaseModel):
    """Response from video upload endpoint."""
    folder: str
    status: str
    message: str


class VideoInfo(BaseModel):
    """Information about a processed video."""
    folder: str
    name: str
    timestamp: int
    user_id: str
    has_data: bool
    has_renders: bool


class VideoListResponse(BaseModel):
    """Response from list videos endpoint."""
    videos: List[VideoInfo]


class StatusResponse(BaseModel):
    """Response from status check endpoint."""
    folder: str
    status: str
    stage: Optional[str] = None
    error: Optional[str] = None
    data_ready: bool = False
    renders_ready: bool = False


class SegmentsResponse(BaseModel):
    """Response from segments endpoint."""
    folder: str
    data: Optional[List[Dict[str, Any]]] = None
    transcript: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class RenderRequest(BaseModel):
    """Request for rendering variants."""
    variants: List[Dict[str, Any]]
    settings: Optional[Dict[str, Any]] = None


class RenderResponse(BaseModel):
    """Response from render endpoint."""
    folder: str
    status: str
    message: str


class RendersResponse(BaseModel):
    """Response from get renders endpoint."""
    folder: str
    combos: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class GenerateVariantsRequest(BaseModel):
    """Request for generating AI variants."""
    prompt: str
    target_duration: Optional[float] = None
    num_variants: int = 5


class GenerateVariantsResponse(BaseModel):
    """Response from generate variants endpoint."""
    variants: List[Dict[str, Any]]
    error: Optional[str] = None


class FileUrlResponse(BaseModel):
    """Response with presigned URL for a file."""
    url: str
    expires_in: int


class SplitSegmentRequest(BaseModel):
    """Request for splitting a segment."""
    segment_id: str
    split_times: List[float]


class SplitSegmentResponse(BaseModel):
    """Response from split segment endpoint."""
    status: str
    message: str

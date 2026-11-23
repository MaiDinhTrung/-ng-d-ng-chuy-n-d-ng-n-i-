from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AspectRatio = Literal["16:9", "9:16", "1:1"]
Category = Literal["character", "environment", "style", "storyboard"]

CATEGORY_LABELS = {
    "character": "Nhân vật",
    "environment": "Bối cảnh",
    "style": "Phong cách hình ảnh",
    "storyboard": "Storyboard",
}


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=5000)
    topic: str = Field("", max_length=2000)
    script: str = Field("", max_length=200_000)
    language: str = Field("vi", max_length=16)
    target_audience: str = Field("", max_length=500)
    video_type: str = Field("", max_length=100)
    duration_sec: int | None = Field(None, ge=1, le=36_000)
    aspect_ratio: AspectRatio = "16:9"
    visual_style: str = Field("", max_length=500)
    voice_engine: str | None = Field(None, max_length=64)
    voice_id: str | None = Field(None, max_length=128)


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    topic: str | None = Field(None, max_length=2000)
    script: str | None = Field(None, max_length=200_000)
    language: str | None = Field(None, max_length=16)
    target_audience: str | None = Field(None, max_length=500)
    video_type: str | None = Field(None, max_length=100)
    duration_sec: int | None = Field(None, ge=1, le=36_000)
    aspect_ratio: AspectRatio | None = None
    visual_style: str | None = Field(None, max_length=500)
    voice_engine: str | None = Field(None, max_length=64)
    voice_id: str | None = Field(None, max_length=128)


class ReferencePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    category: Category | None = None
    tags: list[str] | None = None


class LinkIn(BaseModel):
    note: str = Field("", max_length=1000)


class MetaPatch(BaseModel):
    bgm_volume: float | None = Field(None, ge=0, le=1)
    subtitles: bool | None = None
    default_transition: str | None = Field(None, max_length=32)


class CharacterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=4000)
    facial_features: str = Field("", max_length=2000)
    hair: str = Field("", max_length=1000)
    costume: str = Field("", max_length=2000)
    main_colors: str = Field("", max_length=500)
    weapons: str = Field("", max_length=1000)
    personality: str = Field("", max_length=1000)
    consistency_rules: str = Field("", max_length=2000)
    reference_ids: list[str] = []


class CharacterPatch(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=4000)
    facial_features: str | None = Field(None, max_length=2000)
    hair: str | None = Field(None, max_length=1000)
    costume: str | None = Field(None, max_length=2000)
    main_colors: str | None = Field(None, max_length=500)
    weapons: str | None = Field(None, max_length=1000)
    personality: str | None = Field(None, max_length=1000)
    consistency_rules: str | None = Field(None, max_length=2000)
    reference_ids: list[str] | None = None


class SceneFields(BaseModel):
    title: str | None = Field(None, max_length=300)
    narration: str | None = Field(None, max_length=20000)
    environment: str | None = Field(None, max_length=2000)
    visual_description: str | None = Field(None, max_length=4000)
    camera_angle: str | None = Field(None, max_length=500)
    camera_movement: str | None = Field(None, max_length=32)
    character_action: str | None = Field(None, max_length=2000)
    lighting: str | None = Field(None, max_length=1000)
    duration: float | None = Field(None, ge=1, le=60)
    transition: str | None = Field(None, max_length=32)
    effect: str | None = Field(None, max_length=32)
    image_prompt: str | None = Field(None, max_length=4000)
    negative_prompt: str | None = Field(None, max_length=2000)
    character_ids: list[str] | None = None
    reference_ids: list[str] | None = None


class SceneIn(SceneFields):
    after_idx: int | None = None


class ScenePatch(SceneFields):
    pass


class RegenIn(BaseModel):
    instruction: str = Field("", max_length=2000)


class GenerateImageIn(BaseModel):
    provider_id: str
    n: int = Field(1, ge=1, le=8)
    quality: str = "standard"
    model: str | None = None
    size: str | None = None


class SelectImageIn(BaseModel):
    generation_id: str


class ProduceIn(BaseModel):
    kind: Literal["preview", "final"] = "preview"


class BudgetIn(BaseModel):
    budget_usd: float | None = Field(None, ge=0, le=100000)

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PauseSettings(BaseModel):
    comma: int | None = Field(None, ge=0, le=60000)
    period: int | None = Field(None, ge=0, le=60000)
    ellipsis: int | None = Field(None, ge=0, le=60000)
    newline: int | None = Field(None, ge=0, le=60000)


class ProjectSettingsIn(BaseModel):
    engine: str | None = None
    voice: str | None = None
    speed: float | None = Field(None, ge=0.5, le=2.0)
    pauses: PauseSettings | None = None
    split_commas: bool | None = None
    normalize: bool | None = None

    def clean(self) -> dict:
        d = self.model_dump(exclude_unset=True)
        if "pauses" in d and d["pauses"] is not None:
            d["pauses"] = {k: v for k, v in d["pauses"].items() if v is not None}
        return d


class ProjectCreate(BaseModel):
    name: str = Field("Dự án mới", max_length=120)
    text: str = Field("", max_length=500_000)
    settings: ProjectSettingsIn | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=120)
    settings: ProjectSettingsIn | None = None
    apply_to_segments: list[Literal["voice", "speed"]] | None = None


class ResegmentIn(BaseModel):
    text: str = Field(max_length=500_000)


class SegmentUpdate(BaseModel):
    text: str | None = Field(None, max_length=2000)
    voice: str | None = None
    speed: float | None = Field(None, ge=0.5, le=2.0)
    pause_before: int | None = Field(None, ge=0, le=60000)
    pause_after: int | None = Field(None, ge=0, le=60000)


class SegmentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    after_idx: int | None = None


class GenerateIn(BaseModel):
    force: bool = False
    segment_ids: list[str] | None = None


class PreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    engine: str = "zerotts"
    voice: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    normalize: bool = True


class ExportIn(BaseModel):
    format: Literal["wav", "mp3"] = "wav"
    mode: Literal["merged", "segments"] = "merged"
    output_dir: str | None = None
    mp3_kbps: int = Field(192, ge=64, le=320)


class QuickIn(BaseModel):
    text: str = Field(min_length=1, max_length=3_000_000)
    name: str | None = Field(None, max_length=120)
    engine: str = "zerotts"
    voice: str
    speed: float = Field(1.0, ge=0.5, le=2.0)
    format: Literal["wav", "mp3"] = "wav"
    mp3_kbps: int = Field(192, ge=64, le=320)
    output_dir: str | None = None
    split_commas: bool = False
    pauses: PauseSettings | None = None


class AutoIn(BaseModel):
    format: Literal["wav", "mp3"] = "wav"
    mp3_kbps: int = Field(192, ge=64, le=320)
    output_dir: str | None = None


class SegmentPreviewText(BaseModel):
    text: str
    split_commas: bool = False
    pauses: PauseSettings | None = None

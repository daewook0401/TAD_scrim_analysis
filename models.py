from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PlayerStats(BaseModel):
    name: str | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    cs: int | None = None
    gold: int | None = None


class TeamResult(BaseModel):
    players: list[PlayerStats] = Field(default_factory=list)


class MatchAnalysisResult(BaseModel):
    winner: str | None = None
    team1: TeamResult = Field(default_factory=TeamResult)
    team2: TeamResult = Field(default_factory=TeamResult)


class ScoreboardBBox(BaseModel):
    left: int = 0
    top: int = 0
    right: int = 1000
    bottom: int = 1000


class DraftAnalysis(BaseModel):
    winner: str | None = None
    scoreboard_bbox: ScoreboardBBox = Field(default_factory=ScoreboardBBox)
    team1: TeamResult = Field(default_factory=TeamResult)
    team2: TeamResult = Field(default_factory=TeamResult)


class AnalyzeRequest(BaseModel):
    image_url: str | None = None
    image_path: str | None = None
    bucket: str | None = None
    object_key: str | None = None

    @model_validator(mode="after")
    def validate_input(self) -> "AnalyzeRequest":
        has_url = bool(self.image_url)
        has_path = bool(self.image_path)
        has_object = bool(self.bucket and self.object_key)

        if sum([has_url, has_path, has_object]) != 1:
            raise ValueError("Provide exactly one of image_url, image_path, or bucket+object_key.")
        return self

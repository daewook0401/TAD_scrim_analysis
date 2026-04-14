from __future__ import annotations

import base64
import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from minio import Minio
from openai import OpenAI
from PIL import Image
from dotenv import load_dotenv

from models import DraftAnalysis, MatchAnalysisResult, PlayerStats, ScoreboardBBox, TeamResult


load_dotenv()

IMAGE_ROOT = Path(os.getenv("IMAGE_ROOT", "/data/images")).resolve()
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MAX_SOURCE_WIDTH = int(os.getenv("MAX_SOURCE_WIDTH", "1400"))
MIN_CROP_WIDTH = int(os.getenv("MIN_CROP_WIDTH", "1200"))
MAX_CROP_WIDTH = int(os.getenv("MAX_CROP_WIDTH", "1800"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SECONDS", "60"))

FULL_IMAGE_PROMPT = """
You are analyzing a League of Legends result screenshot.

The screenshot may include top client UI chrome and extra space.
Find the scoreboard area below the tab row that contains labels similar to:
scoreboard, overview, stats, graph, runes.

Return only valid JSON.

Tasks:
1. Estimate the scoreboard bounding box that starts below the tab row and tightly covers both teams.
2. Extract a draft match result from the full image.

Rules:
- team1 is the upper team block in the scoreboard.
- team2 is the lower team block in the scoreboard.
- winner must be exactly one of: "team1", "team2", "unknown".
- scoreboard_bbox values must be integers normalized from 0 to 1000.
- left/top/right/bottom must describe the scoreboard area inside the image.
- Keep player names exactly as seen if readable.
- If unreadable, use null.
- Do not invent names or numbers.
- gold must be integer without commas.
- Ignore champions, items, spells, bans, objective icons, and levels.
- Each team should contain up to 5 visible players.
""".strip()

VALIDATION_PROMPT = """
You are validating a draft JSON extraction for a League of Legends scoreboard crop.

You will receive:
1. A cropped scoreboard image.
2. A draft JSON result.

Return only valid JSON.
Correct the draft only when the image clearly supports the correction.

Rules:
- winner must be exactly one of: "team1", "team2", "unknown".
- team1 is the upper team block.
- team2 is the lower team block.
- Each team must contain exactly 5 player objects.
- Each player object must contain exactly:
  name, kills, deaths, assists, cs, gold
- If a field is unreadable, use null.
- Never invent values.
- Keep names exactly as shown in the image if readable.
- gold must be integer without commas.
- Ignore non-scoreboard information.
""".strip()

FULL_IMAGE_SCHEMA = {
    "name": "scoreboard_draft",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "winner": {"type": "string", "enum": ["team1", "team2", "unknown"]},
            "scoreboard_bbox": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "left": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "top": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "right": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "bottom": {"type": "integer", "minimum": 0, "maximum": 1000},
                },
                "required": ["left", "top", "right", "bottom"],
            },
            "team1": {"$ref": "#/$defs/team"},
            "team2": {"$ref": "#/$defs/team"},
        },
        "required": ["winner", "scoreboard_bbox", "team1", "team2"],
        "$defs": {
            "player": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "kills": {"type": ["integer", "null"]},
                    "deaths": {"type": ["integer", "null"]},
                    "assists": {"type": ["integer", "null"]},
                    "cs": {"type": ["integer", "null"]},
                    "gold": {"type": ["integer", "null"]},
                },
                "required": ["name", "kills", "deaths", "assists", "cs", "gold"],
            },
            "team": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "players": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/player"},
                        "maxItems": 5,
                    }
                },
                "required": ["players"],
            },
        },
    },
}

FINAL_SCHEMA = {
    "name": "scoreboard_final",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "winner": {"type": "string", "enum": ["team1", "team2", "unknown"]},
            "team1": {"$ref": "#/$defs/team"},
            "team2": {"$ref": "#/$defs/team"},
        },
        "required": ["winner", "team1", "team2"],
        "$defs": {
            "player": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "kills": {"type": ["integer", "null"]},
                    "deaths": {"type": ["integer", "null"]},
                    "assists": {"type": ["integer", "null"]},
                    "cs": {"type": ["integer", "null"]},
                    "gold": {"type": ["integer", "null"]},
                },
                "required": ["name", "kills", "deaths", "assists", "cs", "gold"],
            },
            "team": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "players": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/player"},
                        "minItems": 5,
                        "maxItems": 5,
                    }
                },
                "required": ["players"],
            },
        },
    },
}


def analyze_from_request(
    image_url: str | None = None,
    image_path: str | None = None,
    bucket: str | None = None,
    object_key: str | None = None,
) -> MatchAnalysisResult:
    image_bytes = load_source_image(
        image_url=image_url,
        image_path=image_path,
        bucket=bucket,
        object_key=object_key,
    )
    return analyze_image_bytes(image_bytes)


def analyze_local_file(path: str | Path) -> MatchAnalysisResult:
    return analyze_image_bytes(Path(path).read_bytes())


def analyze_image_bytes(image_bytes: bytes) -> MatchAnalysisResult:
    source_image = Image.open(BytesIO(image_bytes)).convert("RGB")

    full_image_bytes = encode_image_for_model(source_image, max_width=MAX_SOURCE_WIDTH)
    draft = first_pass_extract(full_image_bytes)

    cropped_image = crop_scoreboard(source_image, draft.scoreboard_bbox)
    cropped_image_bytes = encode_image_for_model(cropped_image, max_width=MAX_CROP_WIDTH, min_width=MIN_CROP_WIDTH)

    final = second_pass_validate(cropped_image_bytes, draft)
    return normalize_result(final)


def load_source_image(
    *,
    image_url: str | None,
    image_path: str | None,
    bucket: str | None,
    object_key: str | None,
) -> bytes:
    if image_url:
        return download_image(image_url)
    if image_path:
        path = resolve_image_path(image_path)
        return path.read_bytes()
    if bucket and object_key:
        return download_minio_object(bucket, object_key)
    raise ValueError("Either image_url, image_path, or bucket+object_key must be provided.")


def resolve_image_path(image_path: str) -> Path:
    candidate = Path(image_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (IMAGE_ROOT / candidate).resolve()

    try:
        resolved.relative_to(IMAGE_ROOT)
    except ValueError as exc:
        raise ValueError(f"Image path must stay under IMAGE_ROOT: {IMAGE_ROOT}") from exc

    if not resolved.exists():
        raise FileNotFoundError(f"Image not found: {resolved}")

    return resolved


def download_image(url: str) -> bytes:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    return response.content


def download_minio_object(bucket: str, object_key: str) -> bytes:
    client = create_minio_client()
    response = client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def create_minio_client() -> Minio:
    if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
        raise RuntimeError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be set for MinIO object access.")
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def encode_image_for_model(image: Image.Image, *, max_width: int, min_width: int | None = None) -> bytes:
    image = image.convert("RGB")

    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.Resampling.LANCZOS)

    if min_width and image.width < min_width:
        ratio = min_width / image.width
        image = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.Resampling.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90, optimize=True)
    return buffer.getvalue()


def first_pass_extract(image_bytes: bytes) -> DraftAnalysis:
    response = create_client().responses.create(
        model=get_openai_model(),
        input=build_image_input(FULL_IMAGE_PROMPT, image_bytes),
        text={
            "format": {
                "type": "json_schema",
                "name": FULL_IMAGE_SCHEMA["name"],
                "schema": FULL_IMAGE_SCHEMA["schema"],
                "strict": True,
            }
        },
    )
    data = parse_response_json(response.output_text)
    return DraftAnalysis.model_validate(data)


def second_pass_validate(image_bytes: bytes, draft: DraftAnalysis) -> MatchAnalysisResult:
    draft_text = json.dumps(draft.model_dump(exclude={"scoreboard_bbox"}), ensure_ascii=False)
    prompt = f"{VALIDATION_PROMPT}\n\nDraft JSON:\n{draft_text}"

    response = create_client().responses.create(
        model=get_openai_model(),
        input=build_image_input(prompt, image_bytes),
        text={
            "format": {
                "type": "json_schema",
                "name": FINAL_SCHEMA["name"],
                "schema": FINAL_SCHEMA["schema"],
                "strict": True,
            }
        },
    )
    data = parse_response_json(response.output_text)
    return MatchAnalysisResult.model_validate(data)


def build_image_input(prompt: str, image_bytes: bytes) -> list[dict[str, Any]]:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                    "detail": "high",
                },
            ],
        }
    ]


def crop_scoreboard(image: Image.Image, bbox: ScoreboardBBox) -> Image.Image:
    width, height = image.size

    left = clamp(int(width * bbox.left / 1000), 0, width - 1)
    top = clamp(int(height * bbox.top / 1000), 0, height - 1)
    right = clamp(int(width * bbox.right / 1000), left + 1, width)
    bottom = clamp(int(height * bbox.bottom / 1000), top + 1, height)

    return image.crop((left, top, right, bottom))


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def parse_response_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Model response did not contain a JSON object.")
        return json.loads(match.group(0))


def create_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5-mini")


def normalize_result(result: MatchAnalysisResult) -> MatchAnalysisResult:
    return MatchAnalysisResult(
        winner=normalize_winner(result.winner),
        team1=TeamResult(players=normalize_players(result.team1.players)),
        team2=TeamResult(players=normalize_players(result.team2.players)),
    )


def normalize_players(players: list[PlayerStats]) -> list[PlayerStats]:
    normalized = [normalize_player(player) for player in players[:5]]
    while len(normalized) < 5:
        normalized.append(PlayerStats())
    return normalized


def normalize_player(player: PlayerStats) -> PlayerStats:
    return PlayerStats(
        name=normalize_name(player.name),
        kills=normalize_int(player.kills),
        deaths=normalize_int(player.deaths),
        assists=normalize_int(player.assists),
        cs=normalize_int(player.cs),
        gold=normalize_int(player.gold),
    )


def normalize_winner(value: str | None) -> str:
    if value in {"team1", "team2"}:
        return value
    return "unknown"


def normalize_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d-]", "", value)
        return int(cleaned) if cleaned else None
    return None

# TAD Scrim Analysis

League of Legends result screenshots are analyzed with the OpenAI Responses API. The service can read images from MinIO by `bucket` and `object_key`, from a shared local path, from a URL, or from a direct upload.

## Recommended Flow

1. Spring uploads the original image to MinIO.
2. Spring sends `bucket` and `object_key` to the Python API.
3. Python fetches the object through the MinIO API.
4. Python sends the full image to OpenAI for:
   - draft JSON extraction
   - scoreboard bounding box detection
5. Python crops the scoreboard locally using the returned bounding box.
6. Python sends the cropped image and the draft JSON back to OpenAI for validation and correction.
7. Python normalizes the final JSON response.

## API

### `POST /analyze`

Unified JSON endpoint for Spring or any backend caller.

```json
{
  "bucket": "tad",
  "object_key": "11.png"
}
```

### `POST /analyze/object`

```json
{
  "bucket": "tad",
  "object_key": "11.png"
}
```

### `POST /analyze/path`

```json
{
  "image_path": "sample/11.png"
}
```

### `POST /analyze/url`

```json
{
  "image_url": "https://minio.example.com/bucket/path/to/image.png?X-Amz-Signature=..."
}
```

### `POST /analyze/upload`

Send a multipart request with `file`.

## CLI

This can also be called as a shell-style program.

```bash
python analyze_cli.py --bucket tad --object-key 11.png
python analyze_cli.py --image-path sample/11.png
python analyze_cli.py --image-url "https://example.com/11.png"
```

## Response Example

```json
{
  "winner": "team1",
  "team1": {
    "players": [
      {
        "name": "player_name",
        "kills": 6,
        "deaths": 9,
        "assists": 14,
        "cs": 221,
        "gold": 16610
      }
    ]
  },
  "team2": {
    "players": [
      {
        "name": null,
        "kills": null,
        "deaths": null,
        "assists": null,
        "cs": null,
        "gold": null
      }
    ]
  }
}
```

## Environment Variables

- `OPENAI_API_KEY`: required
- `OPENAI_MODEL`: default `gpt-5-mini`
- `MINIO_ENDPOINT`: default `127.0.0.1:9000`
- `MINIO_ACCESS_KEY`: required for `/analyze/object`
- `MINIO_SECRET_KEY`: required for `/analyze/object`
- `MINIO_SECURE`: `true` or `false`, default `false`
- `IMAGE_ROOT`: shared root for relative image paths
- `MAX_SOURCE_WIDTH`: max width for the full-image first pass
- `MIN_CROP_WIDTH`: minimum width for the cropped validation image
- `MAX_CROP_WIDTH`: maximum width for the cropped validation image
- `HTTP_TIMEOUT_SECONDS`: timeout for URL downloads

## Local Run

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

If MinIO runs in a different Docker Compose stack on the same server, do not leave `MINIO_ENDPOINT` as `127.0.0.1:9000`. Inside the container that points back to the analysis container itself, not the host or the MinIO container. Use the server IP or a reachable DNS name instead, for example `MINIO_ENDPOINT=10.0.0.15:9000`.

## Notes

- For same-server MinIO deployments, prefer `bucket` and `object_key` over direct file access.
- Do not read `/data/minio/.../part.1` files directly; use the MinIO API.
- The service keeps cropped validation images large enough for vision OCR by upscaling small scoreboard crops.

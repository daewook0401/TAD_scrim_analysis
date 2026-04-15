from __future__ import annotations

import argparse
import json
import sys

from models import AnalyzeRequest
from service import analyze_from_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a League of Legends result screenshot and print normalized JSON."
    )
    parser.add_argument("--image-path", help="Relative path under IMAGE_ROOT or an absolute local path.")
    parser.add_argument("--image-url", help="Direct image URL.")
    parser.add_argument("--bucket", help="MinIO bucket name.")
    parser.add_argument("--object-key", help="MinIO object key.")
    return parser.parse_args()


def build_request(args: argparse.Namespace) -> AnalyzeRequest:
    return AnalyzeRequest(
        image_path=args.image_path,
        image_url=args.image_url,
        bucket=args.bucket,
        object_key=args.object_key,
    )


def main() -> int:
    try:
        args = parse_args()
        request = build_request(args)
        result = analyze_from_request(
            image_path=request.image_path,
            image_url=request.image_url,
            bucket=request.bucket,
            object_key=request.object_key,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

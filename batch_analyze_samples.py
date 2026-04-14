from __future__ import annotations

import json
from pathlib import Path

from service import analyze_from_request


def main() -> None:
    sample_dir = Path("sample")
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    for index in range(11, 21):
        image_path = sample_dir / f"{index}.png"
        result = analyze_from_request(image_path=str(image_path))
        output_path = output_dir / f"{index}.json"
        output_path.write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"saved: {output_path}")


if __name__ == "__main__":
    main()

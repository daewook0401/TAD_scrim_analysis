from __future__ import annotations

import pytest

from models import AnalyzeRequest


def test_analyze_request_accepts_object_source() -> None:
    request = AnalyzeRequest(bucket="tad", object_key="11.png")

    assert request.bucket == "tad"
    assert request.object_key == "11.png"


def test_analyze_request_rejects_multiple_sources() -> None:
    with pytest.raises(ValueError):
        AnalyzeRequest(image_url="https://example.com/a.png", image_path="sample/a.png")

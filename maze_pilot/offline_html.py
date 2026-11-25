"""Embed JSON payloads and client scripts into offline HTML exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_offline_html(
    *,
    template_path: Path,
    script_path: Path,
    data: Any,
    output: Path,
    data_marker: str,
    script_marker: str,
) -> None:
    """Replace HTML placeholders with compact JSON and the client script."""
    template = template_path.read_text(encoding="utf-8")
    script = script_path.read_text(encoding="utf-8")
    # Compact separators keep file:// exports smaller without changing semantics.
    json_data = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    html = template.replace(data_marker, json_data).replace(script_marker, script)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

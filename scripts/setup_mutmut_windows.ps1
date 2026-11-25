# One-time Windows setup after `uv sync --group mutation`.
$sitePackages = Join-Path $PSScriptRoot ".." ".venv" "Lib" "site-packages"
$sitecustomize = Join-Path $sitePackages "sitecustomize.py"
@'
"""Python startup hook: stub POSIX modules for Windows mutmut workers."""

from __future__ import annotations

import sys
import types

if "resource" not in sys.modules:
    resource = types.ModuleType("resource")
    resource.RLIMIT_CPU = 0
    resource.setrlimit = lambda *args, **kwargs: None
    sys.modules["resource"] = resource
'@ | Set-Content -LiteralPath $sitecustomize -Encoding utf8
Write-Host "Wrote $sitecustomize"
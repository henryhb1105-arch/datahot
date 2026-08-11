#!/usr/bin/env python3
"""Report whether the latest weekly brief is publishable and AI-edited."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from weekly_brief import valid_brief


def inspect_weekly_brief(path, *, expect_ai=False):
    path = Path(path)
    try:
        brief = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        return False, f"周报文件不可用：{type(exc).__name__}"
    if isinstance(brief, dict) and brief.get("status") == "pending":
        reason = str(brief.get("fallback_reason") or "unknown")
        return False, f"周报 {brief.get('week_id')} 仍在整理中（{reason}）"
    if not valid_brief(brief):
        return False, "周报结构、证据引用或 AI 输出不符合发布要求"
    summary = (
        f"周报 {brief.get('week_id')}：{len(brief.get('signals', []))} 个信号，"
        f"{len(brief.get('evidence_index', []))} 条证据，模式 AI，"
        f"生成于 {brief.get('generated_at')}"
    )
    if expect_ai and not brief.get("ai_assisted"):
        reason = str(brief.get("fallback_reason") or "unknown")
        return False, f"{summary}；需要检查 AI 生成链路（{reason}）"
    return True, summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="site/data/weekly_brief.json")
    parser.add_argument("--expect-ai", action="store_true")
    args = parser.parse_args(argv)
    ok, message = inspect_weekly_brief(args.path, expect_ai=args.expect_ai)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

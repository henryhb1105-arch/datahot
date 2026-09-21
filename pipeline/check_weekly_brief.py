#!/usr/bin/env python3
"""Report whether the latest weekly brief is publishable and AI-edited."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weekly_brief import PUBLISH_HOUR, TZ, completed_week, valid_brief


def inspect_weekly_brief(path, *, expect_ai=False, now=None):
    path = Path(path)
    try:
        brief = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        return False, f"周报文件不可用：{type(exc).__name__}"
    if isinstance(brief, dict) and brief.get("status") == "pending":
        reason = str(brief.get("fallback_reason") or "unknown")
        if brief.get("retry_status") == "retry_limit_reached":
            reason = "本周自动重试已达上限，需检查生成链路；" + reason
        elif brief.get("next_retry_at"):
            reason = "下次尝试 " + str(brief["next_retry_at"]) + "；" + reason
        return False, f"周报 {brief.get('week_id')} 仍在整理中（{reason}）"
    if not valid_brief(brief):
        return False, "周报结构、证据引用或 AI 输出不符合发布要求"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    expected = completed_week(current.astimezone(TZ) - timedelta(hours=PUBLISH_HOUR))["week_id"]
    if brief.get("week_id") != expected:
        return False, f"周报已过期：应发布 {expected}，当前仍为 {brief.get('week_id')}"
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
    if os.getenv("GITHUB_ACTIONS") == "true":
        if not ok:
            escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::warning title=周报需要检查::{escaped}")
        summary = os.getenv("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as output:
                output.write("\n### 周报状态\n\n" + message + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

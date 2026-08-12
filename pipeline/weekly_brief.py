#!/usr/bin/env python3
"""Generate a validated weekly signal report and Henry's personal brief."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from lite_data import event_timestamp, is_list_eligible
from weekly_schema import (
    PERSONAL_RESPONSE_SCHEMA, SIGNAL_RESPONSE_SCHEMA, validate_json_schema,
)


TZ = timezone(timedelta(hours=8))
SCHEMA_VERSION = 3
SIGNAL_SCHEMA_VERSION = 1
INPUT_SCHEMA_VERSION = 1
PROMPT_VERSION = "weekly-personal-v2"
SIGNAL_PROMPT_VERSION = "weekly-signals-v1"
MIN_ITEMS = 10
MAX_ITEMS = 15
MAX_EVIDENCE_ITEMS = 60
WEEKLY_SOURCE_CAP = 2
MIN_IMPORTANCE = 45
PUBLISH_HOUR = 8
CACHE_WEEKS = 26
BASELINE_WEEKS = 4
CATEGORY_LABELS = {
    "agent": "Data Agent",
    "platform": "AI 数据平台",
    "bi": "BI 与可视化",
    "product": "数据产品",
    "insight": "AI 分析与洞察",
}
STRONG_TREND_WORDS = ("进入", "转向", "成为主流", "全面", "普遍", "行业已经")
MECHANISM_KEYWORDS = (
    "Data Agent", "Agent", "语义层", "语义约束", "工作流", "评估", "人机协作",
    "行动窗口", "投入产出", "支出", "返工", "迁移", "实时分析", "ChatBI",
    "SSD", "推理存储", "数据库修复", "数据网格", "知识库", "RAG",
)


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean_text(value, maximum):
    return " ".join(str(value or "").split())[:maximum]


def _event_datetime(event):
    parsed = event_timestamp(event)
    return parsed.astimezone(TZ) if parsed else None


def completed_week(value):
    """Return the most recently completed Monday-Sunday Beijing week."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        local_date = value.astimezone(TZ).date()
    elif isinstance(value, date):
        local_date = value
    else:
        local_date = date.fromisoformat(str(value))
    current_monday = local_date - timedelta(days=local_date.weekday())
    period_end = current_monday - timedelta(days=1)
    period_start = period_end - timedelta(days=6)
    iso = period_end.isocalendar()
    return {
        "week_id": f"{iso.year}-W{iso.week:02d}",
        "period_start": period_start,
        "period_end": period_end,
    }


def _week_for_dates(period_start, period_end=None):
    start = date.fromisoformat(period_start) if isinstance(period_start, str) else period_start
    end = period_end or (start + timedelta(days=6))
    end = date.fromisoformat(end) if isinstance(end, str) else end
    iso = end.isocalendar()
    return {
        "week_id": f"{iso.year}-W{iso.week:02d}",
        "period_start": start,
        "period_end": end,
    }


def _publication_ready(local_now):
    if local_now.weekday() != 0:
        return True
    ready_at = datetime.combine(local_now.date(), time(PUBLISH_HOUR), tzinfo=TZ)
    return local_now >= ready_at


def normalize_source_family(source):
    source = str(source or "").casefold()
    source = re.sub(r"[（(][^）)]*[）)]", " ", source)
    source = re.sub(
        r"\b(?:official|engineering|blog|blogs|news|medium|rss)\b", " ", source,
    )
    source = re.sub(r"(?:官方网站|官方博客|官网|官方|博客|动态|中文|英文)$", "", source)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", source)


def _primary_source(event):
    if event.get("source"):
        return str(event.get("source") or "")
    items = event.get("items") or []
    return str(items[0].get("source") or "") if items else ""


def _source_type(event):
    source = _primary_source(event).casefold()
    if any(token in source for token in ("官方", "博客", "动态", "engineering", "blog")):
        return "vendor_claim"
    if any(token in source for token in ("techcrunch", "infoq", "极客公园", "产品经理")):
        return "media_report"
    return "other"


def select_weekly_events(events, period_start, period_end, limit=MAX_ITEMS):
    """Return 10-15 high-value canonical events from one completed week."""
    if isinstance(period_start, str):
        period_start = date.fromisoformat(period_start)
    if isinstance(period_end, str):
        period_end = date.fromisoformat(period_end)
    candidates = []
    for event in events:
        published_at = _event_datetime(event)
        event_id = str(event.get("event_id") or "")
        if (
            published_at is None
            or not period_start <= published_at.date() <= period_end
            or not re.fullmatch(r"[0-9a-f]{12}", event_id)
            or not is_list_eligible(event)
            or int(event.get("importance") or 0) < MIN_IMPORTANCE
        ):
            continue
        candidates.append(event)
    candidates.sort(
        key=lambda event: (
            int(event.get("heat") or 0),
            int(event.get("importance") or 0),
            len(event.get("items") or []),
            _event_datetime(event) or datetime.min.replace(tzinfo=TZ),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )

    selected, selected_ids, source_counts = [], set(), Counter()

    def add(event):
        source = _primary_source(event)
        family = normalize_source_family(source)
        if not source or not family or source_counts[family] >= WEEKLY_SOURCE_CAP:
            return False
        selected.append(event)
        selected_ids.add(event["event_id"])
        source_counts[family] += 1
        return True

    for category in CATEGORY_LABELS:
        match = next((
            event for event in candidates
            if event.get("category") == category
            and source_counts[normalize_source_family(_primary_source(event))]
            < WEEKLY_SOURCE_CAP
        ), None)
        if match is not None:
            add(match)

    target = max(MIN_ITEMS, min(MAX_ITEMS, int(limit or MAX_ITEMS)))
    for event in candidates:
        if len(selected) >= target:
            break
        if event["event_id"] not in selected_ids:
            add(event)
    selected.sort(
        key=lambda event: (
            int(event.get("heat") or 0), int(event.get("importance") or 0),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )
    return selected


def select_weekly_evidence(
    events, period_start, period_end, limit=MAX_EVIDENCE_ITEMS,
):
    """Return the completed week's full qualified canonical evidence pool."""
    if isinstance(period_start, str):
        period_start = date.fromisoformat(period_start)
    if isinstance(period_end, str):
        period_end = date.fromisoformat(period_end)
    candidates, seen_ids = [], set()
    for event in events:
        published_at = _event_datetime(event)
        event_id = str(event.get("event_id") or "")
        if (
            published_at is None
            or not period_start <= published_at.date() <= period_end
            or not re.fullmatch(r"[0-9a-f]{12}", event_id)
            or event_id in seen_ids
            or not is_list_eligible(event)
            or int(event.get("importance") or 0) < MIN_IMPORTANCE
        ):
            continue
        candidates.append(event)
        seen_ids.add(event_id)
    candidates.sort(
        key=lambda event: (
            int(event.get("importance") or 0),
            int(event.get("heat") or 0),
            len(event.get("items") or []),
            _event_datetime(event) or datetime.min.replace(tzinfo=TZ),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )
    return candidates[:max(1, int(limit or MAX_EVIDENCE_ITEMS))]


def _stable_items(events, *, week_id=""):
    rows = []
    for event in events:
        source = _primary_source(event)
        sources = [
            str(item.get("source") or "").strip()
            for item in event.get("items", []) if item.get("source")
        ] or ([source] if source else [])
        primary = (event.get("items") or [{}])[0]
        rows.append({
            "event_id": str(event.get("event_id") or ""),
            "title": _clean_text(event.get("zh_title") or event.get("title"), 180),
            "summary": _clean_text(event.get("zh_summary") or event.get("summary"), 420),
            "category": (
                event.get("category") if event.get("category") in CATEGORY_LABELS
                else "platform"
            ),
            "source": _clean_text(source, 100),
            "source_family": normalize_source_family(source),
            "source_type": str(event.get("source_type") or _source_type(event)),
            "source_count": len(set(sources)),
            "source_url": _clean_text(
                event.get("source_url") or primary.get("link"), 800,
            ),
            "published": str(event.get("published") or event.get("first_seen") or ""),
            "heat": max(0, min(100, int(event.get("heat") or 0))),
            "importance": max(0, min(100, int(event.get("importance") or 0))),
            "vendors": [
                _clean_text(value, 80) for value in (event.get("vendors") or [])[:8]
                if _clean_text(value, 80)
            ],
            "topics": [
                _clean_text(value, 80) for value in (event.get("topics") or [])[:8]
                if _clean_text(value, 80)
            ],
            "week_id": str(event.get("week_id") or week_id),
        })
    return rows


def brief_input_hash(events):
    rows = _stable_items(events) if any("items" in item for item in events) else events
    canonical = [
        {
            "event_id": str(event.get("event_id") or ""),
            "title": str(event.get("zh_title") or event.get("title") or "").strip(),
            "summary": str(event.get("zh_summary") or event.get("summary") or "").strip(),
            "category": str(event.get("category") or ""),
            "source_family": str(event.get("source_family") or ""),
            "topics": sorted(str(value) for value in (event.get("topics") or [])),
            "heat": int(event.get("heat") or 0),
        }
        for event in rows
    ]
    return _fingerprint(canonical)


def brief_cache_key(
    week_id, input_hash, prompt_version=PROMPT_VERSION, model="", *,
    baseline_hash="", schema_version=SCHEMA_VERSION,
):
    return _fingerprint({
        "week_id": str(week_id),
        "input_hash": str(input_hash),
        "baseline_hash": str(baseline_hash),
        "prompt_version": str(prompt_version),
        "schema_version": int(schema_version),
        "model": str(model or "unconfigured"),
    })


def _evidence_snapshot(selected, week, input_hash):
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "kind": "weekly_evidence",
        "week_id": week["week_id"],
        "period_start": str(week["period_start"]),
        "period_end": str(week["period_end"]),
        "input_hash": input_hash,
        "items": _stable_items(selected, week_id=week["week_id"]),
    }


def _valid_evidence_snapshot(value, week_id=None):
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != INPUT_SCHEMA_VERSION
        or value.get("kind") != "weekly_evidence"
        or (week_id and value.get("week_id") != week_id)
    ):
        return False
    items = value.get("items")
    return isinstance(items, list) and all(
        isinstance(item, dict)
        and re.fullmatch(r"[0-9a-f]{12}", str(item.get("event_id") or ""))
        for item in items
    )


def _baseline_context(events, week, input_archive_dir):
    desired, documents = [], []
    for offset in range(1, BASELINE_WEEKS + 1):
        start = week["period_start"] - timedelta(days=7 * offset)
        prior = _week_for_dates(start)
        desired.append(prior["week_id"])
        selected = select_weekly_evidence(
            events, prior["period_start"], prior["period_end"],
        )
        document = None
        if selected:
            prior_hash = brief_input_hash(selected)
            document = _evidence_snapshot(selected, prior, prior_hash)
        elif input_archive_dir:
            candidate = _load_json(Path(input_archive_dir) / f"{prior['week_id']}.json", {})
            if _valid_evidence_snapshot(candidate, prior["week_id"]):
                document = candidate
        if document:
            documents.append(document)

    rows = []
    for document in documents:
        for item in document.get("items", []):
            row = dict(item)
            row["week_id"] = document["week_id"]
            rows.append(row)
    return {
        "requested_weeks": BASELINE_WEEKS,
        "requested_week_ids": desired,
        "available_weeks": len(documents),
        "available_week_ids": [document["week_id"] for document in documents],
        "coverage": "complete" if len(documents) == BASELINE_WEEKS else (
            "partial" if documents else "missing"
        ),
        "items": rows,
    }


def _prompt_event_rows(rows):
    return [
        {
            "event_id": row["event_id"],
            "week_id": row.get("week_id", ""),
            "title": row.get("title", ""),
            "summary": row.get("summary", ""),
            "category": row.get("category", ""),
            "source": row.get("source", ""),
            "source_family": row.get("source_family", ""),
            "source_type": row.get("source_type", ""),
            "vendors": row.get("vendors", []),
            "topics": row.get("topics", []),
            "importance": row.get("importance", 0),
        }
        for row in rows
    ]


def _signals_prompt(current_rows, baseline, week, daily_candidates=None):
    schema_hint = {
        "weekly_judgement": "本周相较过去发生了什么，不超过180字",
        "signals": [{
            "signal_id": "lowercase-kebab-case",
            "title": "具体信号，不超过32字",
            "change_type": "early_signal/new/strengthening/continuing/cooling/unknown",
            "confidence": "high/medium/low",
            "confidence_reason": "证据独立性与基线依据",
            "anchor": "具体产品、公司、能力、案例或数字锚点",
            "mechanism": "为什么这些事件属于同一个产品或技术机制",
            "baseline_comparison": "与过去4周比较",
            "evidence_ids": ["合法event_id"],
            "counter_evidence": "反证或缺口",
        }],
        "signals_not_promoted": [{
            "label": "未上升为趋势的候选",
            "reason": "为何证据不足或事件异质",
            "evidence_ids": ["合法event_id"],
        }],
        "uncertainty": "本期最大的证据缺口",
        "next_week_question": "下周最值得验证的问题",
    }
    instructions = (
        "你是 AIHot 的周度行业信号分析器。你的任务不是写周报，也不是汇总新闻，而是判断"
        "相较此前4周，哪些产品或技术机制真正新出现、增强、延续或降温。\n"
        "硬性规则：\n"
        "1. 先按同一产品机制聚类。不得因为事件都涉及AI、成本或可靠性就合并。\n"
        "2. 同一发布的转载只算一个事件；source_family相同不算独立证据。\n"
        "3. 没有历史基线时，change_type只能是early_signal或unknown。\n"
        "4. 单一供应商或单一客户案例只能是early_signal，不得为high。\n"
        "5. 至少两个独立证据方向一致，才可标记strengthening。\n"
        "6. 每个信号必须保留具体事实锚点、反证或证据缺口。\n"
        "7. 允许输出0到3个信号。宁缺毋滥，禁止凑满数量。\n"
        "8. 本周原始事件是事实输入；日报候选只帮助发现主题，不能替代原始证据。\n"
        "9. 不得添加输入中不存在的事实、公司、数字和事件。\n"
        "10. 只输出一个JSON对象，不得使用Markdown代码围栏，不得在对象前后写说明。"
    )
    payload = {
        "period": {
            "week_id": week["week_id"],
            "period_start": str(week["period_start"]),
            "period_end": str(week["period_end"]),
        },
        "baseline": {
            key: baseline[key] for key in (
                "requested_weeks", "requested_week_ids", "available_weeks",
                "available_week_ids", "coverage",
            )
        },
        "current_events": _prompt_event_rows(current_rows),
        "baseline_events": _prompt_event_rows(baseline["items"]),
        "daily_candidate_hints": daily_candidates or [],
        "output_shape": schema_hint,
    }
    return instructions + "\n输入：" + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
    )


def _personal_prompt(signal_doc, evidence_map):
    allowed_ids = []
    for signal in signal_doc["signals"]:
        allowed_ids.extend(signal["evidence_ids"])
    allowed_ids = list(dict.fromkeys(allowed_ids))
    evidence = [
        {"event_id": event_id, "title": evidence_map[event_id]["title"]}
        for event_id in allowed_ids if event_id in evidence_map
    ]
    input_value = {
        "week_id": signal_doc["week_id"],
        "period_start": signal_doc["period_start"],
        "period_end": signal_doc["period_end"],
        "weekly_judgement": signal_doc["weekly_judgement"],
        "signals": signal_doc["signals"],
        "signals_not_promoted": signal_doc["signals_not_promoted"],
        "uncertainty": signal_doc["uncertainty"],
        "next_week_question": signal_doc["next_week_question"],
        "evidence_titles": evidence,
    }
    return (
        "你是 Henry 的每周 AI 与数据行业情报编辑。\n\n"
        "输入是一份已经通过证据校验的周报分析结果。请将其改写成适合 Henry 阅读的个人周报。\n\n"
        "读者关注 AI 产品落地、Agent 工作流、数据基础设施，以及成本、可靠性和可维护性。"
        "他希望快速知道什么真正发生了变化、与自己有什么关系、是否需要行动，不需要重新浏览新闻。\n\n"
        "写作要求：\n"
        "1. 正文必须达到800至1200个汉字，3分钟内读完；中文、字母、数字和标点均按1个字符计算。\n"
        "2. 先给结论，再解释机制，最后给行动或观察建议。\n"
        "3. 最多3个主题，允许0至2个，不得凑满。\n"
        "4. 每个主题必须通过signal_id引用输入信号，并说明这对你意味着什么。\n"
        "5. priority只能是现在行动、安排测试、继续观察或暂时忽略。\n"
        "6. 没有行动价值时明确写暂时无需行动。\n"
        "7. 不得添加输入中不存在的事实、公司、数字和事件。\n"
        "8. 不逐条复述新闻；资讯标题只出现在evidence_index。\n"
        "9. early_signal或unknown不得改写为已经进入、转向或成为主流。\n"
        "10. 不得修改信号的change_type、confidence、anchor或evidence_ids。\n"
        "11. 不使用加速发展、持续演进、值得关注、赋能、闭环等空泛表述。\n"
        "12. 只输出一个JSON对象，不得使用Markdown代码围栏，不得在对象前后写说明。\n"
        "13. 按最终保留主题数控制各字段长度，不得用重复结论凑字数：1个主题时，insight 230至260字、"
        "why_it_matters 210至240字、action 170至200字；2个主题时，每项依次130至160字、"
        "110至140字、80至110字；3个主题时，每项依次90至120字、70至100字、50至80字。\n"
        "14. title 12至24字，bottom_line 30至60字，what_not_to_overread和uncertainty各60至100字，"
        "next_week_question 30至60字。\n\n"
        "输出JSON字段固定为title、bottom_line、for_you、what_not_to_overread、uncertainty、"
        "next_week_question、evidence_index。for_you每项字段固定为signal_id、priority、insight、"
        "why_it_matters、action。evidence_index每项只含event_id和原始title。\n输入："
        + json.dumps(input_value, ensure_ascii=False, separators=(",", ":"))
    )


def _event_tags(row):
    text = f"{row.get('title', '')} {row.get('summary', '')}".casefold()
    tags = {str(value).strip().casefold() for value in row.get("topics", []) if value}
    for keyword in MECHANISM_KEYWORDS:
        if keyword.casefold() in text:
            tags.add(keyword.casefold())
    return tags


def _cohesive_evidence(event_ids, evidence_map):
    if len(event_ids) <= 2:
        return True
    tag_sets = [_event_tags(evidence_map[event_id]) for event_id in event_ids]
    if any(not tags for tags in tag_sets):
        return False
    reached = {0}
    changed = True
    while changed:
        changed = False
        for index, tags in enumerate(tag_sets):
            if index in reached:
                continue
            if any(tags & tag_sets[other] for other in reached):
                reached.add(index)
                changed = True
    return len(reached) == len(tag_sets)


def _anchor_grounded(anchor, rows):
    combined = " ".join(
        f"{row.get('title', '')} {row.get('summary', '')} "
        f"{' '.join(row.get('topics', []))} {' '.join(row.get('vendors', []))}"
        for row in rows
    ).casefold()
    anchor_folded = str(anchor).casefold()
    for row in rows:
        for value in list(row.get("vendors", [])) + list(row.get("topics", [])):
            token = str(value).strip().casefold()
            if len(token) >= 2 and token in anchor_folded:
                return True
    for number in re.findall(r"\d+(?:\.\d+)?%?", anchor_folded):
        if number in combined:
            return True
    for token in re.findall(r"[a-z][a-z0-9.+-]{2,}", anchor_folded):
        if token in combined:
            return True
    compact = re.sub(r"[^\u4e00-\u9fff]", "", anchor_folded)
    generic = {"本周出现", "数据平台", "分析产品", "人工智能", "行业信号", "多个事件"}
    for width in (6, 5, 4):
        for index in range(max(0, len(compact) - width + 1)):
            token = compact[index:index + width]
            if token not in generic and token in combined:
                return True
    return False


def validate_signal_response(response, evidence_map, current_ids, baseline):
    errors = validate_json_schema(response, SIGNAL_RESPONSE_SCHEMA)
    if errors:
        return errors
    signal_ids = [signal["signal_id"] for signal in response["signals"]]
    if len(signal_ids) != len(set(signal_ids)):
        errors.append("$.signals: signal_id must be unique")
    allowed = set(evidence_map)
    current_ids = set(current_ids)
    baseline_available = int(baseline.get("available_weeks") or 0)
    for index, signal in enumerate(response["signals"]):
        path = f"$.signals[{index}]"
        evidence_ids = signal["evidence_ids"]
        unknown = [event_id for event_id in evidence_ids if event_id not in allowed]
        if unknown:
            errors.append(f"{path}.evidence_ids: unknown event_id")
            continue
        if not set(evidence_ids) & current_ids:
            errors.append(f"{path}.evidence_ids: at least one current-week event is required")
        rows = [evidence_map[event_id] for event_id in evidence_ids]
        families = {row.get("source_family") for row in rows if row.get("source_family")}
        vendor_sets = [set(row.get("vendors") or []) for row in rows]
        one_vendor = bool(vendor_sets) and all(vendor_sets) and bool(
            set.intersection(*vendor_sets)
        )
        single_case = len(evidence_ids) == 1 or len(families) <= 1 or one_vendor
        if baseline_available == 0 and signal["change_type"] not in {"early_signal", "unknown"}:
            errors.append(f"{path}.change_type: missing baseline only allows early_signal or unknown")
        if single_case and signal["change_type"] not in {"early_signal", "unknown"}:
            errors.append(f"{path}.change_type: single supplier or case cannot establish a trend")
        if single_case and signal["confidence"] == "high":
            errors.append(f"{path}.confidence: single supplier or case cannot be high")
        if signal["change_type"] == "strengthening" and len(families) < 2:
            errors.append(f"{path}: strengthening requires two source families")
        if signal["confidence"] == "high" and (
            len(evidence_ids) < 3 or len(families) < 2 or baseline_available < BASELINE_WEEKS
        ):
            errors.append(f"{path}.confidence: high requires 3 events, 2 families and full baseline")
        if not _cohesive_evidence(evidence_ids, evidence_map):
            errors.append(f"{path}.evidence_ids: heterogeneous evidence does not share one mechanism")
        if not _anchor_grounded(signal["anchor"], rows):
            errors.append(f"{path}.anchor: anchor is not grounded in evidence")
    for index, item in enumerate(response["signals_not_promoted"]):
        if any(event_id not in allowed for event_id in item["evidence_ids"]):
            errors.append(f"$.signals_not_promoted[{index}].evidence_ids: unknown event_id")
    return errors


def _personal_prose_length(response):
    values = [
        response.get("title", ""), response.get("bottom_line", ""),
        response.get("what_not_to_overread", ""), response.get("uncertainty", ""),
        response.get("next_week_question", ""),
    ]
    for item in response.get("for_you", []):
        values.extend([
            item.get("insight", ""), item.get("why_it_matters", ""), item.get("action", ""),
        ])
    return sum(len(str(value)) for value in values)


def _fit_personal_summary(value, maximum, minimum):
    """Keep short display summaries within schema limits without adding facts."""
    text = " ".join(str(value or "").split())
    if len(text) <= maximum:
        return text
    for marker in ("。", "；", "，", "："):
        boundary = text.find(marker)
        if minimum <= boundary <= maximum:
            return text[:boundary].rstrip()
    return text[:maximum].rstrip("，。；：、 ")


def _normalize_personal_response(response):
    if not isinstance(response, dict):
        return response
    normalized = dict(response)
    normalized["title"] = _fit_personal_summary(response.get("title"), 24, 4)
    normalized["bottom_line"] = _fit_personal_summary(
        response.get("bottom_line"), 80, 16,
    )
    return normalized


def _overstates_early_signal(text):
    text = str(text or "")
    negations = ("不足", "不能", "尚未", "没有", "无法", "并未", "不代表", "未能")
    for word in STRONG_TREND_WORDS:
        start = 0
        while True:
            index = text.find(word, start)
            if index < 0:
                break
            if not any(marker in text[max(0, index - 16):index] for marker in negations):
                return True
            start = index + len(word)
    return False


def validate_personal_response(response, signal_doc, evidence_map):
    errors = validate_json_schema(response, PERSONAL_RESPONSE_SCHEMA)
    if errors:
        return errors
    signals = {signal["signal_id"]: signal for signal in signal_doc["signals"]}
    selected_ids = [item["signal_id"] for item in response["for_you"]]
    if len(selected_ids) != len(set(selected_ids)):
        errors.append("$.for_you: signal_id must be unique")
    if any(signal_id not in signals for signal_id in selected_ids):
        errors.append("$.for_you: unknown signal_id")
    for index, item in enumerate(response["for_you"]):
        signal = signals.get(item["signal_id"])
        if signal and signal["change_type"] in {"early_signal", "unknown"}:
            if _overstates_early_signal(item["insight"]):
                errors.append(f"$.for_you[{index}].insight: early signal overstates the trend")
        if item["priority"] == "暂时忽略" and not any(
            marker in item["action"] for marker in ("暂时无需行动", "暂时忽略")
        ):
            errors.append(f"$.for_you[{index}].action: no-action recommendation must be explicit")

    expected_ids = []
    for signal_id in selected_ids:
        for event_id in signals.get(signal_id, {}).get("evidence_ids", []):
            if event_id not in expected_ids:
                expected_ids.append(event_id)
    actual_ids = [item["event_id"] for item in response["evidence_index"]]
    if set(actual_ids) != set(expected_ids) or len(actual_ids) != len(set(actual_ids)):
        errors.append("$.evidence_index: must exactly cover selected signals")
    for index, item in enumerate(response["evidence_index"]):
        row = evidence_map.get(item["event_id"])
        if row is None or item["title"] != row.get("title"):
            errors.append(f"$.evidence_index[{index}]: title must match original evidence")
    prose_length = _personal_prose_length(response)
    if response["for_you"] and not 800 <= prose_length <= 1200:
        errors.append(f"$: personal prose length must be 800-1200 characters, got {prose_length}")
    if not response["for_you"] and prose_length > 600:
        errors.append("$: zero-signal brief must stay concise")
    return errors


def _repair_prompt(original_prompt, errors):
    return (
        original_prompt
        + "\n\n上一次输出未通过校验。只修复下列问题，严格遵守错误中标出的长度上下限，"
        + "中文、字母、数字和标点均按1个字符计算；仍然只输出一个JSON对象：\n- "
        + "\n- ".join(errors[:12])
    )


def _call_validated(llm_generate, prompt, item_id, validator, normalizer=None):
    errors = []
    for attempt in range(2):
        current_prompt = prompt if attempt == 0 else _repair_prompt(prompt, errors)
        try:
            response = llm_generate(
                current_prompt,
                item_id=item_id if attempt == 0 else f"{item_id}:repair",
            )
        except Exception as exc:
            errors = [f"model_error:{type(exc).__name__}:{str(exc)[:160]}"]
            continue
        if normalizer is not None:
            response = normalizer(response)
        errors = validator(response)
        if not errors:
            return response, []
    return None, errors


def _signal_document(response, *, week, now, model, input_hash, baseline_hash,
                     signal_key, baseline, evidence_map):
    used_ids = []
    for signal in response["signals"]:
        used_ids.extend(signal["evidence_ids"])
    for item in response["signals_not_promoted"]:
        used_ids.extend(item["evidence_ids"])
    used_ids = list(dict.fromkeys(used_ids))
    return {
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "kind": "weekly_signals",
        "status": "ready",
        "week_id": week["week_id"],
        "period_start": str(week["period_start"]),
        "period_end": str(week["period_end"]),
        "generated_at": now.isoformat(),
        "ai_assisted": True,
        "content_fingerprint": signal_key,
        "input_hash": input_hash,
        "baseline_hash": baseline_hash,
        "prompt_version": SIGNAL_PROMPT_VERSION,
        "model": model,
        "baseline": {
            key: baseline[key] for key in (
                "requested_weeks", "requested_week_ids", "available_weeks",
                "available_week_ids", "coverage",
            )
        },
        **response,
        "evidence_index": [evidence_map[event_id] for event_id in used_ids],
    }


def valid_signal_document(document, week_id=None):
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != SIGNAL_SCHEMA_VERSION
        or document.get("kind") != "weekly_signals"
        or document.get("status") != "ready"
        or not document.get("ai_assisted")
        or (week_id and document.get("week_id") != week_id)
    ):
        return False
    response = {
        key: document.get(key) for key in (
            "weekly_judgement", "signals", "signals_not_promoted", "uncertainty",
            "next_week_question",
        )
    }
    if validate_json_schema(response, SIGNAL_RESPONSE_SCHEMA):
        return False
    evidence = document.get("evidence_index")
    return isinstance(evidence, list) and all(
        isinstance(item, dict)
        and re.fullmatch(r"[0-9a-f]{12}", str(item.get("event_id") or ""))
        for item in evidence
    )


def _brief_document(response, *, signal_doc, selected, week, now, model, key,
                    input_hash, baseline_hash, evidence_map):
    evidence_ids = [item["event_id"] for item in response["evidence_index"]]
    evidence_rows = [evidence_map[event_id] for event_id in evidence_ids]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "weekly",
        "status": "ready",
        "week_id": week["week_id"],
        "period_start": str(week["period_start"]),
        "period_end": str(week["period_end"]),
        "generated_at": now.isoformat(),
        "mode": "ai",
        "ai_assisted": True,
        "fallback_reason": "",
        "content_fingerprint": key,
        "input_hash": input_hash,
        "baseline_hash": baseline_hash,
        "prompt_version": PROMPT_VERSION,
        "signal_prompt_version": SIGNAL_PROMPT_VERSION,
        "model": model,
        "public_signals_fingerprint": _fingerprint(signal_doc["signals"]),
        "baseline": signal_doc["baseline"],
        "signals": signal_doc["signals"],
        **response,
        "items": evidence_rows,
        "candidate_count": len(selected),
    }


def valid_brief(brief, week_id=None):
    if (
        not isinstance(brief, dict)
        or brief.get("schema_version") != SCHEMA_VERSION
        or brief.get("kind") != "weekly"
        or brief.get("status") != "ready"
        or not brief.get("ai_assisted")
        or (week_id and brief.get("week_id") != str(week_id))
    ):
        return False
    signals = brief.get("signals")
    if not isinstance(signals, list):
        return False
    if brief.get("public_signals_fingerprint") != _fingerprint(signals):
        return False
    evidence_rows = brief.get("items")
    if not isinstance(evidence_rows, list):
        return False
    evidence_map = {
        str(item.get("event_id") or ""): item for item in evidence_rows
        if isinstance(item, dict)
    }
    response = {
        key: brief.get(key) for key in (
            "title", "bottom_line", "for_you", "what_not_to_overread", "uncertainty",
            "next_week_question", "evidence_index",
        )
    }
    return not validate_personal_response(
        response, {"signals": signals}, evidence_map,
    )


def _pending_document(*, week, now, model, input_hash, baseline_hash, reason, selected):
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "weekly",
        "status": "pending",
        "week_id": week["week_id"],
        "period_start": str(week["period_start"]),
        "period_end": str(week["period_end"]),
        "generated_at": now.isoformat(),
        "mode": "pending",
        "ai_assisted": False,
        "fallback_reason": reason,
        "input_hash": input_hash,
        "baseline_hash": baseline_hash,
        "prompt_version": PROMPT_VERSION,
        "signal_prompt_version": SIGNAL_PROMPT_VERSION,
        "model": str(model or "unconfigured"),
        "candidate_count": len(selected),
    }


def _cache_payload(cache, local_now):
    weeks = cache.setdefault("weeks", {})
    entries = cache.setdefault("entries", {})
    signal_weeks = cache.setdefault("signal_weeks", {})
    signal_entries = cache.setdefault("signal_entries", {})
    keep_week_ids = sorted(set(weeks) | set(signal_weeks))[-CACHE_WEEKS:]
    keep_entry_keys = {weeks[item] for item in keep_week_ids if item in weeks}
    keep_signal_keys = {
        signal_weeks[item] for item in keep_week_ids if item in signal_weeks
    }
    cache["version"] = 3
    cache["weeks"] = {item: weeks[item] for item in keep_week_ids if item in weeks}
    cache["entries"] = {
        key: entries[key] for key in keep_entry_keys if key in entries
    }
    cache["signal_weeks"] = {
        item: signal_weeks[item] for item in keep_week_ids if item in signal_weeks
    }
    cache["signal_entries"] = {
        key: signal_entries[key] for key in keep_signal_keys if key in signal_entries
    }
    failures = cache.get("failures", {})
    cache["failures"] = {
        item: failures[item] for item in sorted(failures)[-CACHE_WEEKS:]
    }
    cache["updated_at"] = local_now.isoformat()
    return cache


def generate_weekly_brief(
    events,
    *,
    now,
    model="",
    llm_generate=None,
    cache_path,
    output_path,
    archive_dir=None,
    signals_output_path=None,
    signals_archive_dir=None,
    input_archive_dir=None,
    daily_candidates=None,
    force=False,
):
    """Return ``(brief, status)`` after two validated AI editorial stages."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(TZ)
    if not _publication_ready(local_now):
        return None, "before_publish_time"
    week = completed_week(local_now)
    selected = select_weekly_evidence(
        events, week["period_start"], week["period_end"],
    )
    if len(selected) < MIN_ITEMS:
        return None, "insufficient_items"

    cache_path = Path(cache_path)
    output_path = Path(output_path)
    archive_dir = Path(archive_dir) if archive_dir else None
    signals_output_path = Path(signals_output_path) if signals_output_path else (
        output_path.parent / "weekly_signals.json"
    )
    signals_archive_dir = Path(signals_archive_dir) if signals_archive_dir else (
        archive_dir.parent / "weekly_signals" if archive_dir else None
    )
    input_archive_dir = Path(input_archive_dir) if input_archive_dir else (
        archive_dir.parent / "weekly_inputs" if archive_dir else None
    )

    week_id = week["week_id"]
    input_hash = brief_input_hash(selected)
    current_snapshot = _evidence_snapshot(selected, week, input_hash)
    if input_archive_dir:
        _atomic_json(input_archive_dir / f"{week_id}.json", current_snapshot)
    baseline = _baseline_context(events, week, input_archive_dir)
    baseline_hash = _fingerprint({
        "requested": baseline["requested_week_ids"],
        "available": baseline["available_week_ids"],
        "items": baseline["items"],
    })
    current_rows = current_snapshot["items"]
    all_rows = current_rows + baseline["items"]
    evidence_map = {row["event_id"]: row for row in all_rows}
    current_ids = {row["event_id"] for row in current_rows}

    cache = _load_json(cache_path, {
        "version": 3, "weeks": {}, "entries": {}, "signal_weeks": {},
        "signal_entries": {}, "failures": {},
    })
    weeks = cache.setdefault("weeks", {})
    entries = cache.setdefault("entries", {})
    existing_key = weeks.get(week_id)
    existing_entry = entries.get(existing_key) if existing_key else None
    existing_brief = (
        existing_entry.get("brief") if isinstance(existing_entry, dict) else None
    )
    existing_signals = (
        existing_entry.get("signals") if isinstance(existing_entry, dict) else None
    )
    brief_archive_path = archive_dir / f"{week_id}.json" if archive_dir else None
    signal_archive_path = (
        signals_archive_dir / f"{week_id}.json" if signals_archive_dir else None
    )
    if not force and valid_brief(existing_brief, week_id) and valid_signal_document(
        existing_signals, week_id,
    ):
        _atomic_json(output_path, existing_brief)
        _atomic_json(signals_output_path, existing_signals)
        if brief_archive_path:
            _atomic_json(brief_archive_path, existing_brief)
        if signal_archive_path:
            _atomic_json(signal_archive_path, existing_signals)
        return existing_brief, "weekly_cache_hit"

    if not model or llm_generate is None:
        reason = "llm_unconfigured"
        pending = _pending_document(
            week=week, now=local_now, model=model, input_hash=input_hash,
            baseline_hash=baseline_hash, reason=reason, selected=selected,
        )
        cache.setdefault("failures", {})[week_id] = {
            "reason": reason, "updated_at": local_now.isoformat(),
        }
        _atomic_json(output_path, pending)
        _atomic_json(cache_path, _cache_payload(cache, local_now))
        return pending, "pending_llm"

    signal_key = brief_cache_key(
        week_id, input_hash, SIGNAL_PROMPT_VERSION, model,
        baseline_hash=baseline_hash, schema_version=SIGNAL_SCHEMA_VERSION,
    )
    signal_entries = cache.setdefault("signal_entries", {})
    signal_doc = None if force else signal_entries.get(signal_key)
    if not valid_signal_document(signal_doc, week_id):
        prompt = _signals_prompt(current_rows, baseline, week, daily_candidates)
        try:
            signal_response, errors = _call_validated(
                llm_generate, prompt, f"{week_id}:signals",
                lambda value: validate_signal_response(
                    value, evidence_map, current_ids, baseline,
                ),
            )
        except Exception as exc:
            signal_response, errors = None, [type(exc).__name__[:80]]
        if signal_response is None:
            reason = "signals_invalid:" + ";".join(errors[:3])
            pending = _pending_document(
                week=week, now=local_now, model=model, input_hash=input_hash,
                baseline_hash=baseline_hash, reason=reason, selected=selected,
            )
            cache.setdefault("failures", {})[week_id] = {
                "reason": reason, "updated_at": local_now.isoformat(),
            }
            _atomic_json(output_path, pending)
            _atomic_json(cache_path, _cache_payload(cache, local_now))
            return pending, "pending_signals"
        signal_doc = _signal_document(
            signal_response, week=week, now=local_now, model=model,
            input_hash=input_hash, baseline_hash=baseline_hash, signal_key=signal_key,
            baseline=baseline, evidence_map=evidence_map,
        )
        signal_entries[signal_key] = signal_doc
        cache.setdefault("signal_weeks", {})[week_id] = signal_key

    _atomic_json(signals_output_path, signal_doc)
    if signal_archive_path:
        _atomic_json(signal_archive_path, signal_doc)

    personal_key = brief_cache_key(
        week_id, _fingerprint(signal_doc["signals"]), PROMPT_VERSION, model,
        baseline_hash=baseline_hash, schema_version=SCHEMA_VERSION,
    )
    prompt = _personal_prompt(signal_doc, evidence_map)
    try:
        personal_response, errors = _call_validated(
            llm_generate, prompt, f"{week_id}:personal",
            lambda value: validate_personal_response(value, signal_doc, evidence_map),
            normalizer=_normalize_personal_response,
        )
    except Exception as exc:
        personal_response, errors = None, [type(exc).__name__[:80]]
    if personal_response is None:
        reason = "personal_invalid:" + ";".join(errors[:3])
        pending = _pending_document(
            week=week, now=local_now, model=model, input_hash=input_hash,
            baseline_hash=baseline_hash, reason=reason, selected=selected,
        )
        cache.setdefault("failures", {})[week_id] = {
            "reason": reason, "updated_at": local_now.isoformat(),
        }
        _atomic_json(output_path, pending)
        _atomic_json(cache_path, _cache_payload(cache, local_now))
        return pending, "pending_personal"

    brief = _brief_document(
        personal_response, signal_doc=signal_doc, selected=selected, week=week,
        now=local_now, model=model, key=personal_key, input_hash=input_hash,
        baseline_hash=baseline_hash, evidence_map=evidence_map,
    )
    entries[personal_key] = {"brief": brief, "signals": signal_doc}
    weeks[week_id] = personal_key
    cache.setdefault("failures", {}).pop(week_id, None)
    _atomic_json(cache_path, _cache_payload(cache, local_now))
    _atomic_json(output_path, brief)
    if brief_archive_path:
        _atomic_json(brief_archive_path, brief)
    return brief, "generated_ai"

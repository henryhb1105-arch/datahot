import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402
from check_weekly_brief import inspect_weekly_brief  # noqa: E402
import run_update  # noqa: E402
from weekly_brief import (  # noqa: E402
    BASELINE_WEEKS, PROMPT_VERSION, _personal_prose_length, _stable_items,
    brief_cache_key, brief_input_hash, completed_week, generate_weekly_brief,
    select_weekly_events, select_weekly_evidence, validate_personal_response,
    validate_signal_response, valid_brief,
)
from weekly_schema import SIGNAL_RESPONSE_SCHEMA, validate_json_schema  # noqa: E402


def event(
    number, *, seen="2026-08-05T08:00:00+08:00", category=None,
    heat=None, summary=None, source=None, title=None, topics=None, vendors=None,
):
    categories = ["agent", "platform", "bi", "product"]
    category = category or categories[number % len(categories)]
    event_id = f"{number:012x}"
    source = source or f"Source {number}"
    return {
        "event_id": event_id,
        "zh_title": title or f"事件 {number} 的语义约束与评估实践",
        "zh_summary": summary if summary is not None else (
            f"案例 {number} 把语义约束、人工确认点和评估工作流用于稳定交付，"
            "同时记录行动窗口、返工情况与使用成本。"
        ),
        "reason": f"推荐理由 {number}",
        "category": category,
        "category_label": build_site.CAT_LABEL[category],
        "heat": heat if heat is not None else 95 - number,
        "importance": 80,
        "first_seen": seen,
        "published": seen,
        "vendors": vendors if vendors is not None else [f"Vendor {number}"],
        "topics": topics if topics is not None else ["Data Agent", "评估"],
        "items": [{"source": source, "link": f"https://example.com/{number}"}],
    }


def public_response(events, *, zero=False, change_type="early_signal"):
    if zero:
        return {
            "weekly_judgement": "本周没有形成足以改变产品路线或投入判断的新信号。",
            "signals": [],
            "signals_not_promoted": [],
            "uncertainty": "当前证据数量有限，缺少可用于比较的历史基线。",
            "next_week_question": "下周是否出现两个相互独立且机制一致的产品案例？",
        }
    return {
        "weekly_judgement": "本周更可信的信号集中在分析 Agent 的稳定交付条件和 AI 产品结果衡量。",
        "signals": [
            {
                "signal_id": "agent-stable-delivery",
                "title": "分析 Agent 补齐稳定交付条件",
                "change_type": change_type,
                "confidence": "medium",
                "confidence_reason": "两个不同信源家族都给出具体产品机制，但历史基线仍不完整。",
                "anchor": "语义约束、人工确认点和评估工作流同时出现在两个案例中。",
                "mechanism": "两项实践都把业务口径、人工复核和评估一致性放进同一个分析交付过程。",
                "baseline_comparison": "过去四周暂无完整快照，本期只能识别为早期信号。",
                "evidence_ids": [events[0]["event_id"], events[1]["event_id"]],
                "counter_evidence": "尚无长期故障率、返工率和跨场景复用数据。",
            },
            {
                "signal_id": "ai-outcome-metrics",
                "title": "AI 产品开始补结果衡量",
                "change_type": change_type,
                "confidence": "medium",
                "confidence_reason": "两个独立案例分别覆盖行动时效和投入产出，方向一致但数量有限。",
                "anchor": "行动窗口、返工情况与使用成本被放进同一组结果指标。",
                "mechanism": "产品评价从生成过程延伸到结果是否及时可用，以及成本能否对应可用产出。",
                "baseline_comparison": "过去四周暂无完整快照，本期只能识别为早期信号。",
                "evidence_ids": [events[2]["event_id"], events[3]["event_id"]],
                "counter_evidence": "当前案例口径不同，仍缺少同一任务下的成本与结果对照。",
            },
        ],
        "signals_not_promoted": [],
        "uncertainty": "供应商文章和媒体转述仍占多数，缺少独立客户的长期复盘。",
        "next_week_question": "这些交付和衡量机制能否在独立案例中减少返工并控制成本？",
    }


def personal_response(signal_response, events):
    if not signal_response["signals"]:
        return {
            "title": "本周没有可信的新变化",
            "bottom_line": "证据不足时不拼凑趋势，本周保持原有产品路线和投入节奏。",
            "for_you": [],
            "what_not_to_overread": "零散发布只能作为候选信号，不能直接当成行业趋势。",
            "uncertainty": "缺少历史基线和相互独立的案例。",
            "next_week_question": "下周能否出现机制一致的独立证据？",
            "evidence_index": [],
        }
    response = {
        "title": "分析 Agent 开始比拼稳定交付",
        "bottom_line": "本周更可信的变化是分析 Agent 同时补语义约束、人工确认和评估一致性；结果衡量仍属于早期信号。",
        "for_you": [
            {
                "signal_id": "agent-stable-delivery",
                "priority": "安排测试",
                "insight": (
                    "两个独立来源都把语义约束、人工确认点和评估工作流放进分析交付过程。"
                    "这说明产品展示之外，团队开始具体处理口径变化、结果复核和生产评估差异。"
                    "现有证据仍然不足以证明它已经成为普遍做法，因此本期只把它视为可以验证的早期信号。"
                ),
                "why_it_matters": (
                    "这与你正在推进的取数 Agent、分析 Agent 和语义层工作直接相关。"
                    "如果评估路径与生产路径使用不同业务逻辑，模型升级、口径调整或权限变化后都会重复产生复核工作。"
                    "把这些条件提前写入测试，可以更早发现维护成本，而不是等到用户依赖结果后再补。"
                ),
                "action": (
                    "选择一个真实分析任务安排小范围测试。固定输入数据、语义口径、人工确认点和评估样本，"
                    "让同一套业务逻辑同时用于评估与生产。连续记录失败原因、人工返工次数和口径调整后的结果差异，"
                    "再决定是否扩大使用范围。"
                ),
            },
            {
                "signal_id": "ai-outcome-metrics",
                "priority": "现在行动",
                "insight": (
                    "本周两个案例分别把行动窗口和投入产出放到产品评价中。"
                    "它们没有证明行业已经形成统一指标，却共同暴露了只看调用量、生成时长和回答数量的缺口。"
                    "结果来得太晚、需要人工重做或成本超过可用产出时，表面的使用增长无法说明产品有效。"
                ),
                "why_it_matters": (
                    "这会影响你判断 AI 问数和 Agent 是否值得继续增加投入。"
                    "现有指标如果只覆盖模型调用，很难区分问题出在模型、流程等待、数据口径还是人工确认。"
                    "补齐结果指标以后，产品路线和成本优化才有同一套可比较依据。"
                ),
                "action": (
                    "在现有工作流中加入任务完成时剩余的行动时间、人工返工情况、单次可用结果的模型与人力成本。"
                    "先观察一个完整周期，分别记录成功任务和失败任务，随后再决定优先优化响应速度、工作流程还是模型。"
                ),
            },
        ],
        "what_not_to_overread": (
            "不要把单一客户的收益数字或供应商给出的周期直接外推为普遍结果。"
            "不同任务的口径、数据准备和人工复核成本并不相同，本周材料只能支持方向判断。"
        ),
        "uncertainty": (
            "过去四周缺少完整可重放快照，主要材料又来自供应商文章和媒体转述。"
            "目前无法判断这些机制是本周首次出现、明显增强，还是既有做法被集中发布。"
        ),
        "next_week_question": (
            "能否找到独立客户案例，证明加入语义约束和统一评估路径后，返工减少且单次可用结果成本保持可控？"
        ),
        "evidence_index": [],
    }
    event_map = {item["event_id"]: item for item in events}
    for signal in signal_response["signals"]:
        for event_id in signal["evidence_ids"]:
            if event_id not in {item["event_id"] for item in response["evidence_index"]}:
                response["evidence_index"].append({
                    "event_id": event_id,
                    "title": event_map[event_id]["zh_title"],
                })
    return response


def two_stage_callback(events_by_week, calls=None):
    calls = calls if calls is not None else []

    def fake(_prompt, *, item_id):
        calls.append(item_id)
        week_id = item_id.split(":", 1)[0]
        events = events_by_week[week_id]
        signals = public_response(events)
        return signals if ":signals" in item_id else personal_response(signals, events)

    return fake


def evidence_context(events, week_id="2026-W32"):
    rows = _stable_items(events, week_id=week_id)
    return rows, {row["event_id"]: row for row in rows}


def w32_public_response():
    return {
        "weekly_judgement": (
            "本周最可信的信号是分析 Agent 同时补语义约束、人工确认和生产评估一致性；"
            "结果衡量出现早期共振，基础设施侧仍是分散案例。"
        ),
        "signals": [
            {
                "signal_id": "agent-stable-delivery",
                "title": "分析 Agent 补齐稳定交付条件",
                "change_type": "early_signal",
                "confidence": "medium",
                "confidence_reason": "四个事件来自两个信源家族，机制可以互相连接，但缺少过去四周基线。",
                "anchor": "语义约束、人工确认点和评估工作流同时出现在 Aloudata Agent 与运行时无关工作流材料中。",
                "mechanism": "多源取数、语义口径、人工复核与生产评估一致性共同处理分析结果的稳定交付。",
                "baseline_comparison": "过去四周没有可重放快照，本期只能确认多个同向事件同时出现。",
                "evidence_ids": [
                    "203a40c0d09f", "ded49e4ed330", "ed8330108532", "26c7d5691708",
                ],
                "counter_evidence": "监管材料包含会议预告，其他材料也缺少长期返工率和故障率。",
            },
            {
                "signal_id": "ai-outcome-metrics",
                "title": "AI 产品开始补结果衡量",
                "change_type": "early_signal",
                "confidence": "medium",
                "confidence_reason": "两个独立来源分别讨论行动时效和投入产出，但样本仍少。",
                "anchor": "行动窗口与 AI 支出、生产力和返工情况在两个产品案例中被用于评价结果。",
                "mechanism": "产品评价同时检查结果是否赶上业务行动，以及支出是否换来可用产出。",
                "baseline_comparison": "过去四周没有完整快照，无法确认这是首次出现还是集中发布。",
                "evidence_ids": ["f4962a2fa921", "4d1764cb4a3d"],
                "counter_evidence": "两个案例的业务场景和指标口径不同，尚不能计算共同收益。",
            },
        ],
        "signals_not_promoted": [{
            "label": "分散的基础设施案例",
            "reason": "迁移、推理存储和数据库运维属于不同技术层级，不能合并成同一个周度趋势。",
            "evidence_ids": ["0a099ff0f253", "caa8145425d1", "cf0a8f7b6f35"],
        }],
        "uncertainty": "过去四周基线缺失，且供应商文章与媒体转述占比较高。",
        "next_week_question": "是否出现独立案例证明这些机制能减少返工并控制单次可用结果成本？",
    }


class WeeklyBriefSelectionTests(unittest.TestCase):
    def test_completed_week_uses_beijing_monday_to_sunday(self):
        period = completed_week(datetime(2026, 8, 11, 2, tzinfo=timezone.utc))
        self.assertEqual(period["week_id"], "2026-W32")
        self.assertEqual(str(period["period_start"]), "2026-08-03")
        self.assertEqual(str(period["period_end"]), "2026-08-09")

    def test_week_boundaries_category_coverage_and_limit(self):
        events = [event(i) for i in range(18)]
        events.append(event(30, seen="2026-08-02T23:59:00+08:00", heat=100))
        events.append(event(31, seen="2026-08-10T00:00:00+08:00", heat=100))
        selected = select_weekly_events(events, "2026-08-03", "2026-08-09")
        ids = {item["event_id"] for item in selected}
        self.assertEqual(len(selected), 15)
        self.assertNotIn(f"{30:012x}", ids)
        self.assertNotIn(f"{31:012x}", ids)
        self.assertEqual(
            {item["category"] for item in selected},
            {"agent", "platform", "bi", "product"},
        )

    def test_same_source_family_is_capped_at_two(self):
        variants = [
            event(10, source="Aloudata 博客", heat=99),
            event(11, source="Aloudata 动态", heat=98),
            event(12, source="Aloudata 官方博客", heat=97),
        ]
        diverse = [event(20 + i, source=f"Diverse {i}") for i in range(12)]
        selected = select_weekly_events(
            variants + diverse, "2026-08-03", "2026-08-09",
        )
        self.assertEqual(sum(item in variants for item in selected), 2)

    def test_signal_analysis_reads_full_qualified_evidence_pool(self):
        shared = [event(i, source="One Vendor Blog") for i in range(20)]
        evidence = select_weekly_evidence(
            shared, "2026-08-03", "2026-08-09",
        )
        self.assertEqual(len(evidence), 20)
        self.assertEqual(len({item["event_id"] for item in evidence}), 20)

    def test_low_importance_and_unfinished_items_are_rejected(self):
        strong = [event(i) for i in range(10)]
        weak = event(80, category="bi", heat=100)
        weak["importance"] = 0
        unfinished = event(81, heat=100, summary="")
        selected = select_weekly_events(
            strong + [weak, unfinished], "2026-08-03", "2026-08-09",
        )
        ids = {item["event_id"] for item in selected}
        self.assertNotIn(weak["event_id"], ids)
        self.assertNotIn(unfinished["event_id"], ids)

    def test_cache_key_covers_baseline_prompt_schema_and_model(self):
        events = [event(i) for i in range(10)]
        input_hash = brief_input_hash(events)
        base = brief_cache_key(
            "2026-W32", input_hash, PROMPT_VERSION, "deepseek-v4",
            baseline_hash="base-a", schema_version=3,
        )
        self.assertNotEqual(base, brief_cache_key(
            "2026-W32", input_hash, PROMPT_VERSION, "deepseek-v4",
            baseline_hash="base-b", schema_version=3,
        ))
        self.assertNotEqual(base, brief_cache_key(
            "2026-W32", input_hash, PROMPT_VERSION, "deepseek-v4",
            baseline_hash="base-a", schema_version=4,
        ))


class WeeklySignalValidationTests(unittest.TestCase):
    def test_schema_rejects_extra_text_fields(self):
        response = public_response([event(i) for i in range(4)])
        response["commentary"] = "JSON 前后说明不应进入对象"
        errors = validate_json_schema(response, SIGNAL_RESPONSE_SCHEMA)
        self.assertTrue(any("additional property" in error for error in errors))

    def test_zero_signals_are_valid(self):
        events = [event(i) for i in range(4)]
        rows, evidence_map = evidence_context(events)
        errors = validate_signal_response(
            public_response(events, zero=True), evidence_map,
            {row["event_id"] for row in rows},
            {"available_weeks": 0},
        )
        self.assertEqual(errors, [])

    def test_missing_baseline_rejects_strong_trend_language(self):
        events = [event(i) for i in range(4)]
        rows, evidence_map = evidence_context(events)
        response = public_response(events, change_type="strengthening")
        errors = validate_signal_response(
            response, evidence_map, {row["event_id"] for row in rows},
            {"available_weeks": 0},
        )
        self.assertTrue(any("missing baseline" in error for error in errors))

    def test_single_vendor_cannot_establish_strengthening(self):
        events = [
            event(1, source="Vendor Blog", vendors=["Vendor"], topics=["语义层"]),
            event(2, source="Vendor Engineering", vendors=["Vendor"], topics=["语义层"]),
        ]
        rows, evidence_map = evidence_context(events)
        response = public_response(events + events, change_type="strengthening")
        response["signals"] = [response["signals"][0]]
        errors = validate_signal_response(
            response, evidence_map, {row["event_id"] for row in rows},
            {"available_weeks": BASELINE_WEEKS},
        )
        self.assertTrue(any("single supplier" in error for error in errors))

    def test_three_independent_events_can_be_high_confidence(self):
        events = [
            event(1, source="Source A", topics=["语义层"]),
            event(2, source="Source B", topics=["语义层"]),
            event(3, source="Source C", topics=["语义层"]),
        ]
        rows, evidence_map = evidence_context(events)
        signal = public_response(events + [events[0]], change_type="strengthening")
        signal["signals"] = [signal["signals"][0]]
        signal["signals"][0]["evidence_ids"] = [item["event_id"] for item in events]
        signal["signals"][0]["confidence"] = "high"
        signal["signals"][0]["baseline_comparison"] = "过去四周同类证据逐周增加，本周出现第三个独立来源。"
        errors = validate_signal_response(
            signal, evidence_map, {row["event_id"] for row in rows},
            {"available_weeks": BASELINE_WEEKS},
        )
        self.assertEqual(errors, [])

    def test_w32_heterogeneous_infrastructure_group_is_rejected(self):
        payload = json.loads((ROOT / "site/data/latest.json").read_text(encoding="utf-8"))
        wanted = {"0a099ff0f253", "caa8145425d1", "cf0a8f7b6f35", "63b7989f4b33"}
        events = [item for item in payload["events"] if item["event_id"] in wanted]
        rows, evidence_map = evidence_context(events)
        response = {
            "weekly_judgement": "基础设施开始比较完整运营周期。",
            "signals": [{
                "signal_id": "infra-full-cycle",
                "title": "基础设施比较完整运营周期",
                "change_type": "strengthening",
                "confidence": "medium",
                "confidence_reason": "四个事件都涉及成本或可靠性，但技术层级并不一致。",
                "anchor": "ClickHouse Cloud 迁移与 AI SSD 路线同时出现。",
                "mechanism": "将迁移、推理存储和数据库修复合并为运营周期。",
                "baseline_comparison": "过去四周同类信息数量增加。",
                "evidence_ids": sorted(wanted),
                "counter_evidence": "技术层级、决策主体和成熟度不同。",
            }],
            "signals_not_promoted": [],
            "uncertainty": "缺少相同决策主体下的可比证据。",
            "next_week_question": "能否找到同一基础设施决策下的完整成本案例？",
        }
        errors = validate_signal_response(
            response, evidence_map, set(wanted), {"available_weeks": BASELINE_WEEKS},
        )
        self.assertTrue(any("heterogeneous evidence" in error for error in errors))

    def test_personal_layer_cannot_invent_evidence_title(self):
        events = [event(i) for i in range(4)]
        rows, evidence_map = evidence_context(events)
        signals = public_response(events)
        response = personal_response(signals, events)
        self.assertTrue(800 <= _personal_prose_length(response) <= 1200)
        response["evidence_index"][0]["title"] = "模型编造的标题"
        errors = validate_personal_response(
            response, {"signals": signals["signals"]}, evidence_map,
        )
        self.assertTrue(any("title must match" in error for error in errors))


class WeeklyBriefGenerationTests(unittest.TestCase):
    def paths(self, directory):
        root = Path(directory)
        return root / "cache.json", root / "brief.json", root / "weekly"

    def test_ready_week_is_immutable_and_does_not_call_ai_twice(self):
        calls = []
        events = [event(i) for i in range(15)]
        callback = two_stage_callback({"2026-W32": events}, calls)
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            first, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=callback,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            events[0]["zh_summary"] = "同周后续回填改变了输入"
            second, second_status = generate_weekly_brief(
                events, now=datetime(2026, 8, 16, 8, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=callback,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertEqual(status, "generated_ai")
        self.assertEqual(second_status, "weekly_cache_hit")
        self.assertEqual(calls, ["2026-W32:signals", "2026-W32:personal"])
        self.assertEqual(first["content_fingerprint"], second["content_fingerprint"])
        self.assertTrue(valid_brief(first))

    def test_w32_regression_keeps_two_themes_and_drops_infra_composite(self):
        payload = json.loads((ROOT / "site/data/latest.json").read_text(encoding="utf-8"))
        events = payload["events"]
        signals = w32_public_response()

        def callback(_prompt, *, item_id):
            return signals if ":signals" in item_id else personal_response(signals, events)

        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=callback,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertEqual(status, "generated_ai")
        self.assertTrue(valid_brief(brief))
        self.assertEqual(len(brief["for_you"]), 2)
        self.assertEqual(
            {item["signal_id"] for item in brief["for_you"]},
            {"agent-stable-delivery", "ai-outcome-metrics"},
        )
        self.assertNotIn("infra-full-cycle", {item["signal_id"] for item in brief["signals"]})

    def test_pending_rule_placeholder_upgrades_to_ai(self):
        events = [event(i) for i in range(10)]
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            pending, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="", llm_generate=None,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            ready, ready_status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 8, tzinfo=timezone.utc),
                model="deepseek-v4",
                llm_generate=two_stage_callback({"2026-W32": events}, calls),
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertEqual(status, "pending_llm")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(ready_status, "generated_ai")
        self.assertTrue(valid_brief(ready))
        self.assertEqual(len(calls), 2)

    def test_invalid_signals_retry_and_remain_pending(self):
        events = [event(i) for i in range(10)]
        calls = []

        def invalid(_prompt, *, item_id):
            calls.append(item_id)
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            first, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=invalid,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            second, second_status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 8, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=invalid,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertEqual(status, "pending_signals")
        self.assertEqual(second_status, "pending_signals")
        self.assertEqual(first["status"], "pending")
        self.assertEqual(second["status"], "pending")
        self.assertEqual(len(calls), 4)

    def test_model_format_error_gets_one_repair_attempt(self):
        events = [event(i) for i in range(10)]
        calls = []

        def callback(_prompt, *, item_id):
            calls.append(item_id)
            signals = public_response(events)
            if item_id == "2026-W32:signals":
                raise ValueError("response contained Markdown wrapper")
            return signals if ":signals" in item_id else personal_response(signals, events)

        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=callback,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertEqual(status, "generated_ai")
        self.assertTrue(valid_brief(brief))
        self.assertEqual(calls[:2], ["2026-W32:signals", "2026-W32:signals:repair"])

    def test_personal_failure_reuses_valid_public_signals(self):
        events = [event(i) for i in range(10)]
        phase = {"personal_valid": False}
        calls = []

        def callback(_prompt, *, item_id):
            calls.append(item_id)
            signals = public_response(events)
            if ":signals" in item_id:
                return signals
            return personal_response(signals, events) if phase["personal_valid"] else {}

        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            _brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=callback,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            phase["personal_valid"] = True
            brief, second_status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 8, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=callback,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertEqual(status, "pending_personal")
        self.assertEqual(second_status, "generated_ai")
        self.assertEqual(sum(":signals" in item for item in calls), 1)
        self.assertTrue(valid_brief(brief))

    def test_new_week_uses_previous_input_snapshot_as_baseline(self):
        week_32 = [event(i) for i in range(10)]
        week_33 = [event(20 + i, seen="2026-08-12T08:00:00+08:00") for i in range(10)]
        calls = []
        callback = two_stage_callback({"2026-W33": week_33}, calls)
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            generate_weekly_brief(
                week_32, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="", llm_generate=None,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            brief, status = generate_weekly_brief(
                week_33, now=datetime(2026, 8, 18, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=callback,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            self.assertTrue((archive.parent / "weekly_inputs/2026-W32.json").exists())
            self.assertTrue((archive.parent / "weekly_inputs/2026-W33.json").exists())
            self.assertTrue((archive.parent / "weekly_signals/2026-W33.json").exists())
            self.assertTrue((archive / "2026-W33.json").exists())
        self.assertEqual(status, "generated_ai")
        self.assertEqual(brief["baseline"]["available_weeks"], 1)

    def test_monday_waits_until_publish_time_then_stays_pending_without_ai(self):
        events = [event(20 + i, seen="2026-08-12T08:00:00+08:00") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 16, 18, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=lambda *_args, **_kwargs: {},
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            self.assertIsNone(brief)
            self.assertEqual(status, "before_publish_time")
            self.assertFalse(output.exists())
            brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 17, 0, 17, tzinfo=timezone.utc),
                model="", llm_generate=None,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertEqual(status, "pending_llm")
        self.assertEqual(brief["week_id"], "2026-W33")

    def test_fewer_than_ten_items_waits_without_call_or_cache(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            brief, status = generate_weekly_brief(
                [event(i) for i in range(9)],
                now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4",
                llm_generate=lambda *args, **kwargs: calls.append(args),
                cache_path=cache, output_path=output, archive_dir=archive,
            )
        self.assertIsNone(brief)
        self.assertEqual(status, "insufficient_items")
        self.assertFalse(calls)
        self.assertFalse(cache.exists())

    def test_run_update_uses_strict_two_stage_calls_and_manual_force_only(self):
        events = [event(i) for i in range(10)]
        config = ("key", "https://example.test", "deepseek-v4")
        now = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)

        def response_for_call(*_args, **kwargs):
            signals = public_response(events)
            return signals if ":signals" in kwargs["item_id"] else personal_response(signals, events)

        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            with patch.object(run_update, "llm_chat", side_effect=response_for_call) as chat:
                brief, status = run_update.generate_weekly_brief_for_events(
                    events, config, now,
                    cache_path=cache, output_path=output, archive_dir=archive,
                )
            self.assertEqual(status, "generated_ai")
            self.assertTrue(brief["ai_assisted"])
            self.assertEqual(chat.call_count, 2)
            self.assertTrue(all(call.kwargs["strict_object"] for call in chat.call_args_list))
            self.assertEqual(
                {call.kwargs["source"] for call in chat.call_args_list},
                {"weekly_signals", "weekly_personal"},
            )

            with patch.dict(
                run_update.os.environ,
                {"WEEKLY_BRIEF_FORCE": "true", "GITHUB_EVENT_NAME": "schedule"},
                clear=False,
            ):
                with patch.object(run_update, "llm_chat") as scheduled:
                    _brief, cache_status = run_update.generate_weekly_brief_for_events(
                        events, config, now,
                        cache_path=cache, output_path=output, archive_dir=archive,
                    )
            self.assertEqual(cache_status, "weekly_cache_hit")
            scheduled.assert_not_called()

            with patch.dict(
                run_update.os.environ,
                {"WEEKLY_BRIEF_FORCE": "true", "GITHUB_EVENT_NAME": "workflow_dispatch"},
                clear=False,
            ):
                with patch.object(
                    run_update, "llm_chat", side_effect=response_for_call,
                ) as manual:
                    _brief, manual_status = run_update.generate_weekly_brief_for_events(
                        events, config, now,
                        cache_path=cache, output_path=output, archive_dir=archive,
                    )
            self.assertEqual(manual_status, "generated_ai")
            self.assertEqual(manual.call_count, 2)

    def test_feature_switch_stops_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            with patch.dict(run_update.os.environ, {"WEEKLY_BRIEF_ENABLED": "false"}, clear=False):
                with patch.object(run_update, "llm_chat") as chat:
                    brief, status = run_update.generate_weekly_brief_for_events(
                        [event(i) for i in range(10)], ("key", "base", "model"),
                        datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                        cache_path=cache, output_path=output, archive_dir=archive,
                    )
        self.assertIsNone(brief)
        self.assertEqual(status, "disabled")
        chat.assert_not_called()


class WeeklyBriefBuildTests(unittest.TestCase):
    def make_brief(self, events):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4",
                llm_generate=two_stage_callback({"2026-W32": events}),
                cache_path=root / "cache.json", output_path=root / "brief.json",
                archive_dir=root / "weekly",
            )
            self.assertEqual(status, "generated_ai")
            return brief

    def test_page_uses_signal_cards_and_collapsed_evidence(self):
        events = [event(i) for i in range(15)]
        brief = self.make_brief(events)
        teaser = build_site.render_weekly_brief_teaser(brief)
        page = build_site.render_weekly_brief_page(brief, events, "", archives=[brief])
        self.assertIn('href="weekly.html" data-analytics="weekly_brief"', teaser)
        self.assertIn("2026-08-03 至 2026-08-09", page)
        self.assertIn('href="weekly/2026-W32.html"', page)
        self.assertEqual(page.count('class="weekly-theme"'), 2)
        self.assertIn("具体锚点", page)
        self.assertIn("这对你意味着什么", page)
        self.assertIn("证据索引 · 4 条（默认折叠）", page)
        self.assertIn("<details class=\"weekly-evidence\">", page)
        self.assertNotIn("<details class=\"weekly-evidence\" open>", page)
        self.assertNotIn("本周必读", page)
        self.assertNotIn("快速浏览", page)
        for item in brief["evidence_index"]:
            self.assertEqual(page.count(item["title"]), 1)

    def test_archived_page_falls_back_to_original_source(self):
        events = [event(i) for i in range(10)]
        brief = self.make_brief(events)
        page = build_site.render_weekly_brief_page(
            brief, [], "", prefix="../", archives=[brief], archive_prefix="",
        )
        self.assertNotIn('href="../e/', page)
        self.assertIn('href="https://example.com/', page)
        self.assertIn("原始信源 ↗", page)
        self.assertIn('href="2026-W32.html"', page)

    def test_empty_teaser_and_pending_file_show_waiting_state(self):
        teaser = build_site.render_weekly_brief_teaser(None)
        self.assertIn('class="weekly-waiting"', teaser)
        self.assertNotIn('class="weekly-teaser"', teaser)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "brief.json"
            path.write_text(json.dumps({
                "schema_version": 3, "kind": "weekly", "status": "pending",
            }), encoding="utf-8")
            self.assertIsNone(build_site.load_weekly_brief(path))


class WeeklyBriefHealthTests(unittest.TestCase):
    def test_pending_is_not_publishable_and_ready_ai_is_publishable(self):
        events = [event(i) for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "brief.json"
            generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="", llm_generate=None, cache_path=root / "cache.json",
                output_path=output, archive_dir=root / "weekly",
            )
            pending_ok, pending_message = inspect_weekly_brief(output)
            generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 8, tzinfo=timezone.utc),
                model="deepseek-v4",
                llm_generate=two_stage_callback({"2026-W32": events}),
                cache_path=root / "cache.json", output_path=output,
                archive_dir=root / "weekly",
            )
            ready_ok, ready_message = inspect_weekly_brief(output, expect_ai=True)
        self.assertFalse(pending_ok)
        self.assertIn("整理中", pending_message)
        self.assertTrue(ready_ok)
        self.assertIn("2 个信号", ready_message)


class StrictJsonTests(unittest.TestCase):
    def test_weekly_parser_rejects_text_outside_json(self):
        self.assertEqual(run_update.parse_llm_json_content('{"ok":true}', strict_object=True), {"ok": True})
        with self.assertRaises(ValueError):
            run_update.parse_llm_json_content('完成\n{"ok":true}', strict_object=True)
        with self.assertRaises(ValueError):
            run_update.parse_llm_json_content('```json\n{"ok":true}\n```', strict_object=True)


if __name__ == "__main__":
    unittest.main()

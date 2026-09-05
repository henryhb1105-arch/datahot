"""Evidence-backed design studies, independent of the rolling news feed.

Study IDs and local media references are stable. Adding an evergreen study must
not manufacture a news event or change publication dates in latest.json.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlsplit

from product_cases import DESIGN_QUESTIONS, PRODUCT_TYPES, TASK_TYPES
from case_visuals import detail_image, focus_caption

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "pipeline/design_studies.json"
ASSETS = ROOT / "pipeline/assets/case-media"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MEDIA = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+\.(?:png|jpg|webp)$")
COMPARISON_SLUGS = ("metabase-metabot", "wren-classic", "sagemaker-notebook")
COMPARISON_TITLE = "AI 给出结果后，用户如何修改和验证？"
COMPARISON_ROWS = (("edit", "如何修改"), ("verify", "如何核验"), ("recover", "如何恢复"), ("fit", "适用条件 · DataHot 判断"))


def esc(value):
    return html.escape(str(value or ""), quote=True)


def https_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password)
    except ValueError:
        return False


def case_id(study):
    return study.get("event_id") or hashlib.sha256(
        ("design-study:" + study["slug"]).encode()
    ).hexdigest()[:12]


def study_path(study):
    return "cases/" + study["slug"] + ".html"


def validate_studies(payload, events=(), *, site_root=None, assets_root=None):
    """Fail closed on missing evidence, unsafe paths, or broken step references."""
    errors = []
    if not isinstance(payload, dict) or payload.get("schema_version") != "design-studies-v1":
        return ["invalid design study schema"]
    studies = payload.get("studies")
    if not isinstance(studies, list):
        return ["studies must be a list"]
    event_map = {e["event_id"]: e for e in events}
    seen, seen_ids = set(), set()
    for index, study in enumerate(studies):
        label = f"studies[{index}]"
        if not isinstance(study, dict):
            errors.append(f"{label}: must be an object")
            continue
        slug = study.get("slug", "")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug) or slug in seen:
            errors.append(f"{label}: invalid or duplicate slug")
            continue
        seen.add(slug)
        identifier = case_id(study)
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{12}", identifier) or identifier in seen_ids:
            errors.append(f"{label}: invalid or duplicate case id")
            continue
        seen_ids.add(identifier)
        for field in ("product", "title", "audience", "problem", "takeaway", "version_note", "limits"):
            if not isinstance(study.get(field), str) or not study[field].strip():
                errors.append(f"{label}: missing {field}")
        if study.get("material_type") not in ("产品截图", "官方演示", "架构/方法参考"):
            errors.append(f"{label}: invalid material_type")
        if study.get("product_type") not in PRODUCT_TYPES or study.get("task_type") not in TASK_TYPES:
            errors.append(f"{label}: invalid product/task type")
        for field in ("modules", "design_questions"):
            values = study.get(field)
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
                errors.append(f"{label}: invalid {field}")
        if isinstance(study.get("design_questions"), list) and any(q not in DESIGN_QUESTIONS for q in study["design_questions"]):
            errors.append(f"{label}: unknown design question")
        try:
            observed = date.fromisoformat(study.get("observed_at", ""))
            if observed > date.today():
                errors.append(f"{label}: observed_at is in the future")
        except (TypeError, ValueError):
            errors.append(f"{label}: invalid observed_at")
        source_map = {}
        sources = study.get("sources", [])
        if not isinstance(sources, list) or not sources:
            errors.append(f"{label}: requires evidence sources")
            sources = []
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not source.get("id") or not source.get("title") or not https_url(source.get("url")):
                errors.append(f"{label}: invalid evidence source")
                continue
            if source["id"] in source_map:
                errors.append(f"{label}: duplicate evidence source")
            source_map[source["id"]] = source
        event = event_map.get(study.get("event_id"))
        if study.get("event_id") and event is None:
            errors.append(f"{label}: original event missing")
        steps = study.get("steps", [])
        if not isinstance(steps, list) or not 3 <= len(steps) <= 6:
            errors.append(f"{label}: requires 3-6 evidenced steps")
            steps = []
        hero = study.get("hero_step")
        if type(hero) is not int or not 1 <= hero <= len(steps):
            errors.append(f"{label}: invalid hero_step")
        for step in steps:
            if not isinstance(step, dict):
                errors.append(f"{label}: step must be an object")
                continue
            for field in ("title", "action", "feedback", "focus", "insight"):
                if not isinstance(step.get(field), str) or not step[field].strip():
                    errors.append(f"{label}: step missing {field}")
            if step.get("source_id") not in source_map:
                errors.append(f"{label}: step source missing")
            if bool(step.get("asset")) == bool(step.get("figure_id")):
                errors.append(f"{label}: step needs exactly one image reference")
            if step.get("asset"):
                asset = step["asset"]
                if not isinstance(asset, str) or not MEDIA.fullmatch(asset) or not asset.startswith(slug + "/"):
                    errors.append(f"{label}: unsafe asset path")
                elif assets_root is not None:
                    path = Path(assets_root) / asset
                    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size < 8_000_000:
                        errors.append(f"{label}: missing or oversized image {asset}")
                if not https_url(step.get("image_url")):
                    errors.append(f"{label}: missing original image URL")
            if step.get("figure_id"):
                figure = next((b for b in (event or {}).get("content_blocks", []) if b.get("type") == "figure" and b.get("id") == step["figure_id"]), {})
                cached = str(figure.get("cached_src") or "")
                if not re.fullmatch(r"\.\./media/" + re.escape(study.get("event_id", "")) + r"/[a-zA-Z0-9_-]+\.(?:png|jpg|webp)", cached):
                    errors.append(f"{label}: figure missing or unsafe")
                elif site_root is not None and not (Path(site_root) / cached.removeprefix("../")).is_file():
                    errors.append(f"{label}: cached figure file missing")
        lessons = study.get("lessons", [])
        if not isinstance(lessons, list) or not 1 <= len(lessons) <= 3:
            errors.append(f"{label}: requires 1-3 lessons")
            lessons = []
        for lesson in lessons:
            if not isinstance(lesson, dict):
                errors.append(f"{label}: lesson must be an object")
                continue
            for field in ("title", "why", "when", "cost"):
                if not isinstance(lesson.get(field), str) or not lesson[field].strip():
                    errors.append(f"{label}: lesson missing {field}")
            refs = lesson.get("steps", [])
            if not isinstance(refs, list) or not refs or any(type(n) is not int or not 1 <= n <= len(steps) for n in refs):
                errors.append(f"{label}: lesson evidence missing")
        comparison = study.get("comparison")
        if comparison is not None:
            if not isinstance(comparison, dict):
                errors.append(f"{label}: comparison must be an object")
                continue
            for key, _ in COMPARISON_ROWS:
                cell = comparison.get(key, {})
                if not isinstance(cell, dict) or not cell.get("text") or type(cell.get("step")) is not int or not 1 <= cell["step"] <= len(steps):
                    errors.append(f"{label}: comparison evidence missing for {key}")
    return errors


def load_studies(events, path=MANIFEST, *, site_root=ROOT / "site", assets_root=ASSETS):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_studies(payload, events, site_root=site_root, assets_root=assets_root)
    if errors:
        raise ValueError("invalid design studies:\n" + "\n".join(errors))
    return payload["studies"]


def resolved_steps(study, events):
    event = next((e for e in events if e.get("event_id") == study.get("event_id")), {})
    figures = {b.get("id"): b for b in event.get("content_blocks", []) if b.get("type") == "figure"}
    sources = {s["id"]: s for s in study["sources"]}
    result = []
    for step in study["steps"]:
        source = sources[step["source_id"]]
        src = ("case-media/" + step["asset"]) if step.get("asset") else figures[step["figure_id"]]["cached_src"].removeprefix("../")
        anchor = step.get("source_anchor", "")
        result.append({**step, "src": src, "source_title": source["title"], "source_url": source["url"] + ("#" + quote(anchor) if anchor else "")})
    return result


def library_records(product_cases, events, studies):
    """Project standalone studies into library cards only; never into news feeds."""
    by_id = {case_id(s): s for s in studies}
    event_map = {e["event_id"]: e for e in events}
    cards = []
    for case in product_cases:
        cards.append({**case, "study": by_id.get(case["event_id"])})
    for study in studies:
        if study.get("event_id"):
            continue
        identifier = case_id(study)
        if identifier in event_map:
            raise ValueError("standalone study id collides with a news event")
        cards.append({
            "event_id": identifier, "product": study["product"], "product_type": study["product_type"],
            "task_type": study["task_type"], "design_questions": study["design_questions"],
            "user_problem": study["problem"], "takeaways": [study["takeaway"]],
            "datahot_interpretation": [study["lessons"][0]["why"]], "modules": study["modules"],
            "tradeoffs": [study["limits"]], "interactions": [s["title"] for s in study["steps"]],
            "observed_at": study["observed_at"], "study": study,
        })
        event_map[identifier] = {"event_id": identifier, "items": [{"source": study["product"]}], "category": "product"}
    return cards, event_map


def viewer_markup():
    return '''<dialog class="case-image-dialog" data-image-dialog aria-labelledby="caseImageTitle">
  <header><h2 id="caseImageTitle" data-image-title>查看界面</h2><button type="button" data-image-close autofocus>关闭</button></header>
  <div class="case-image-canvas" data-image-canvas><img data-image-full alt=""></div>
  <footer><button type="button" data-image-prev aria-label="上一张界面">← 上一张</button><span data-image-count aria-live="polite"></span><button type="button" data-image-next aria-label="下一张界面">下一张 →</button><button type="button" data-image-zoom aria-pressed="false">原尺寸</button><a data-image-case hidden>查看案例 →</a></footer>
</dialog>'''


def render_study_body(study, studies, events, bookmark_icon):
    steps = resolved_steps(study, events)
    identifier = case_id(study)
    snapshot = {"event_id": identifier, "title": study["product"] + " · " + study["title"], "summary": study["takeaway"], "source": study["sources"][0]["title"], "category": "product", "topics": ["产品设计", *study["design_questions"]], "original_url": study["sources"][0]["url"], "detail_path": study_path(study)}
    question_links = "".join(f'<a href="../cases.html?question={quote(q)}">{esc(q)}</a>' for q in study["design_questions"])
    nav = "".join(f'<button type="button" data-step-select="{i}" aria-controls="step-{i}" aria-pressed="false"><span>{i:02d}</span>{esc(step["title"])}</button>' for i, step in enumerate(steps, 1))
    panels = []
    for i, step in enumerate(steps, 1):
        panels.append(f'''<section class="study-step" id="step-{i}" data-study-step="{i}" aria-labelledby="stepTitle{i}">
  <figure><a class="study-image" href="../{esc(step['src'])}" data-case-image data-image-group="{esc(study['slug'])}" data-image-caption="{esc(step['title'])}" aria-label="放大：{esc(step['title'])}">{detail_image("../" + step['src'], step['title'] + " — " + step['focus'], 'loading="lazy"' if i > 1 else 'fetchpriority="high"')}<span>点击放大 ↗</span></a>
  <figcaption>{focus_caption(step['src'])}{esc(study['material_type'])} · <a href="{esc(step['source_url'])}" target="_blank" rel="noopener noreferrer">{esc(step['source_title'])} ↗</a></figcaption></figure>
  <div class="study-step-copy"><p class="study-step-number">操作 {i:02d} / {len(steps):02d}</p><h2 id="stepTitle{i}">{esc(step['title'])}</h2>
    <dl><dt>用户操作</dt><dd>{esc(step['action'])}</dd><dt>系统反馈 · 公开材料</dt><dd>{esc(step['feedback'])}</dd><dt>看图重点</dt><dd>{esc(step['focus'])}</dd></dl>
    <div class="study-insight"><b>DataHot 解读</b><p>{esc(step['insight'])}</p></div>
  </div>
</section>''')
    lessons = []
    for lesson in study["lessons"]:
        refs = " · ".join(f'<a href="#step-{n}">操作 {n:02d}</a>' for n in lesson["steps"])
        lessons.append(f'''<article><h3>{esc(lesson['title'])}</h3><p>{esc(lesson['why'])}</p><dl><dt>适合</dt><dd>{esc(lesson['when'])}</dd><dt>代价</dt><dd>{esc(lesson['cost'])}</dd></dl><p class="study-evidence">对应证据：{refs}</p></article>''')
    related = sorted((s for s in studies if s["slug"] != study["slug"]), key=lambda s: -len(set(s["design_questions"]) & set(study["design_questions"])))[:2]
    related_html = "".join(f'<a href="{esc(s["slug"])}.html"><b>{esc(s["product"])}</b><span>{esc(s["takeaway"])}</span></a>' for s in related)
    sources_html = "".join(f'<li><a href="{esc(s["url"])}" target="_blank" rel="noopener noreferrer">{esc(s["title"])} ↗</a> · {esc(s["kind"])}</li>' for s in study["sources"])
    original = f'<a href="../e/{esc(study["event_id"])}.html">阅读站内原文 →</a>' if study.get("event_id") else ""
    comparison = f'<a class="study-compare-link" href="compare.html">同题对比：{COMPARISON_TITLE} →</a>' if study.get("comparison") else ""
    context = esc(json.dumps({"topics": ["产品设计"], "source": study["product"]}, ensure_ascii=False))
    return f'''<main class="wrap study-page" data-study-page data-event-id="{identifier}">
  <a class="study-back" href="../cases.html">← 数据产品设计库</a>
  <header class="study-header"><p class="study-product">{esc(study['product'])} · {esc(study['material_type'])}</p><h1>{esc(study['title'])}</h1>
    <p class="study-problem">{esc(study['problem'])}</p><div class="study-header-bottom"><span>{esc(study['audience'])}</span><button class="favbtn study-save" type="button" data-fav="{identifier}" data-fav-record="{esc(json.dumps(snapshot, ensure_ascii=False))}" aria-label="收藏案例" aria-pressed="false">{bookmark_icon}<span class="sbtn-label">收藏案例</span></button></div>
  </header>
  <nav class="study-step-nav" aria-label="关键操作" data-step-nav hidden>{nav}</nav>
  <div class="study-steps">{''.join(panels)}</div>
  <div class="study-step-controls" data-step-controls hidden><button type="button" data-step-prev>← 上一步</button><span data-step-status aria-live="polite"></span><button type="button" data-step-next>下一步 →</button></div>
  <p class="study-version">{esc(study['version_note'])} · 核对于 {esc(study['observed_at'])}</p>
  <section class="study-lessons"><h2>迁移到你的产品 · DataHot 判断</h2><div>{''.join(lessons)}</div></section>
  <p class="study-limits"><b>未验证与边界</b>{esc(study['limits'])}</p>
  {comparison}
  <section class="study-related"><h2>看看其他做法</h2><div>{related_html}</div><nav class="study-question-links" aria-label="相关设计问题">{question_links}</nav></section>
  <section class="study-sources"><h2>资料出处</h2><ul>{sources_html}</ul>{original}</section>
  <section class="study-feedback content-feedback" data-content-feedback data-feedback-kind="design" data-event-id="{identifier}" data-feedback-context="{context}" aria-label="案例反馈"><h2>对你的产品设计有帮助吗？</h2><div><button type="button" data-feedback-value="useful" aria-pressed="false">有帮助</button><button type="button" data-feedback-value="not_useful" aria-pressed="false">帮助不大</button></div><p data-feedback-status aria-live="polite">反馈与收藏分开保存在当前设备。</p></section>
</main>{viewer_markup()}<script defer src="../design-studies.js"></script><script defer src="../content-feedback.js"></script>'''


def render_comparison_body(studies, events):
    by_slug = {s["slug"]: s for s in studies}
    selected = [by_slug[slug] for slug in COMPARISON_SLUGS]
    heads = []
    for study in selected:
        step_no = study["comparison"]["edit"]["step"]
        step = resolved_steps(study, events)[step_no - 1]
        heads.append(f'''<th scope="col"><a href="{esc(study['slug'])}.html">{esc(study['product'])}</a><a href="../{esc(step['src'])}" data-case-image data-image-group="comparison" data-image-caption="{esc(study['product'])}：{esc(step['title'])}"><img src="../{esc(step['src'])}" alt="{esc(step['title'])}，点击放大" decoding="async"></a></th>''')
    rows = []
    for key, label in COMPARISON_ROWS:
        cells = []
        for study in selected:
            cell = study["comparison"][key]
            cells.append(f'<td><a class="study-comparison-product" href="{esc(study["slug"])}.html">{esc(study["product"])}</a><p>{esc(cell["text"])}</p><a href="{esc(study["slug"])}.html#step-{cell["step"]}">查看操作 {cell["step"]:02d} 的证据 →</a></td>')
        rows.append(f'<tr><th scope="row">{esc(label)}</th>{"".join(cells)}</tr>')
    return f'''<main class="wrap study-page study-comparison"><a class="study-back" href="../cases.html">← 数据产品设计库</a><header class="study-header"><p class="study-product">同一个设计问题 · 三种做法</p><h1>{COMPARISON_TITLE}</h1><p class="study-problem">比较控制权放在哪里，以及用户如何检查、修改和恢复。下表只记录材料支持的行为，不评价模型准确率。</p></header><p class="study-version">Wren 为 GenBI Classic 历史界面；空缺能力写“未展示”，不等于产品没有。</p><div class="study-comparison-scroll" tabindex="0" role="region" aria-label="三种结果纠偏方式对比"><table><thead><tr><th scope="col">设计问题</th>{''.join(heads)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div><section class="study-decision"><h2>如何选用 · DataHot 判断</h2><p>已有 SQL 工作台：优先研究 Metabase 的差异审阅；用户更懂业务模型：参考 Wren 的步骤与 SQL 双通道；已有多引擎 Notebook：研究 SageMaker 的单元格上下文和就地修复。三者都仍需你设计结果核验与权限边界。</p></section></main>{viewer_markup()}<script defer src="../design-studies.js"></script>'''

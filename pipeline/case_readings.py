"""Image-first reading for existing cases without inventing a walkthrough.

Each view reuses the curated case and cached source figures. Figure order is a
reading order (representative figure first), never evidence of an action flow.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from design_studies import esc, https_url, viewer_markup
from product_cases import find_case_hero
from case_visuals import detail_image, focus_caption


def reading_path(case):
    identifier = str(case.get("event_id", ""))
    if not re.fullmatch(r"[a-f0-9]{12}", identifier):
        raise ValueError("invalid reference case id")
    return f"cases/case-{identifier}.html"


def material_type(case):
    return {
        "c93bfa7909b8": "架构/方法参考",
        "6c6fc36a363b": "架构/方法参考",
        "bd501c61d0f5": "官方示意",
        "c90518881d01": "官方示意",
        "83357b7d65a2": "社区实操截图",
    }.get(case["event_id"], "产品截图")


def reading_figures(case, event):
    hero = find_case_hero(event, case)
    if hero is None:
        raise ValueError("reference case requires its curated hero")
    pattern = re.compile(r"\.\./media/" + re.escape(case["event_id"]) + r"/[a-zA-Z0-9_-]+\.(?:png|jpe?g|webp)$")
    figures, seen = [], set()
    heading, paragraph = "", ""
    for block in event.get("content_blocks", []):
        if block.get("type") == "heading":
            heading = str(block.get("text") or "")
            paragraph = ""
        elif block.get("type") == "paragraph":
            paragraph = str(block.get("text") or "")
        if block.get("type") != "figure" or not pattern.fullmatch(str(block.get("cached_src", ""))):
            continue
        if block["cached_src"] in seen:
            continue
        seen.add(block["cached_src"])
        caption = str(block.get("caption") or block.get("alt") or "").strip()
        if re.fullmatch(r"(?:image|img)?[\w-]*\.(?:png|jpg|webp)", caption, re.I):
            caption = ""
        figures.append({**block, "reading_caption": caption, "reading_heading": heading,
                        "reading_context": paragraph[:360] + ("…" if len(paragraph) > 360 else "")})
    figures.sort(key=lambda figure: figure["id"] != hero["id"])
    if not figures or figures[0]["id"] != hero["id"]:
        raise ValueError("reference hero has an unsafe media path")
    return figures


def reference_sources(event):
    sources, seen = [], set()
    for item in event.get("items", []):
        url = item.get("link") or item.get("url")
        if https_url(url) and url not in seen:
            sources.append({"url": url, "title": item.get("source") or item.get("title") or "原文来源"})
            seen.add(url)
    if not sources:
        raise ValueError("reference case requires a public source")
    return sources


def render_reading_body(case, event, bookmark_icon):
    identifier = case["event_id"]
    figures, sources = reading_figures(case, event), reference_sources(event)
    snapshot = {"event_id": identifier, "title": case["product"], "summary": case["takeaways"][0],
                "source": sources[0]["title"], "category": "product", "topics": ["产品设计", *case["design_questions"]],
                "original_url": sources[0]["url"], "detail_path": reading_path(case)}
    navigation, panels = [], []
    for index, figure in enumerate(figures, 1):
        label = "代表界面" if index == 1 and material_type(case) == "产品截图" else ("代表配图" if index == 1 else f"原文配图 {index}")
        caption = figure["reading_caption"]
        title = caption if caption and len(caption) <= 32 else label
        navigation.append(f'<button type="button" data-step-select="{index}" aria-controls="step-{index}" aria-pressed="false"><span>{index:02d}</span>{esc(title)}</button>')
        source_url = figure.get("source_url") if https_url(figure.get("source_url")) else sources[0]["url"]
        context = figure["reading_context"]
        if index == 1:
            copy = f'<dl><dt>要解决的问题</dt><dd>{esc(case["user_problem"])}</dd></dl><div class="study-insight"><b>可以借鉴 · DataHot 解读</b><p>{esc(case["takeaways"][0])}</p></div>'
        else:
            context_html = f'<dt>原文上下文</dt><dd>{esc(context)}</dd>' if context else ''
            copy = f'<dl><dt>配图说明</dt><dd>{esc(caption or "原文未单独提供图注，可打开完整原文结合上下文阅读。")}</dd>{context_html}</dl>'
        panels.append(f'''<section class="study-step" id="step-{index}" data-study-step="{index}" aria-labelledby="stepTitle{index}">
  <figure><a class="study-image" href="{esc(figure['cached_src'])}" data-case-image data-image-group="case-{identifier}" data-image-caption="{esc(case['product'])} · {esc(title)}" aria-label="放大：{esc(title)}">{detail_image(figure['cached_src'], caption or case['product'] + ' · ' + label, 'loading="lazy"' if index > 1 else 'fetchpriority="high"')}<span>查看完整原图 ↗</span></a><figcaption>{focus_caption(figure['cached_src'])}{esc(material_type(case))} · <a href="{esc(source_url)}" target="_blank" rel="noopener noreferrer">{esc(sources[0]['title'])} ↗</a>{(' · ' + esc(caption)) if caption else ''}</figcaption></figure>
  <div class="study-step-copy"><p class="study-step-number">配图 {index:02d} / {len(figures):02d}</p><h2 id="stepTitle{index}">{esc(title)}</h2>{copy}</div>
</section>''')
    blocks = []
    for title, field in (("公开材料说明", "official_facts"), ("DataHot 解读", "datahot_interpretation"),
                         ("功能模块", "modules"), ("交互方式 · 案例整理", "interactions"),
                         ("可以借鉴", "takeaways"), ("收益与代价", "tradeoffs")):
        items = ''.join(f'<li>{esc(value)}</li>' for value in case[field])
        blocks.append(f'<article><h3>{title}</h3><ul>{items}</ul></article>')
    limits = ' '.join(case['limitations'])
    source_links = ''.join(f'<li><a href="{esc(source["url"])}" target="_blank" rel="noopener noreferrer">{esc(source["title"])} ↗</a></li>' for source in sources)
    questions = ''.join(f'<a href="../cases.html?question={quote(question)}">{esc(question)}</a>' for question in case['design_questions'])
    context = esc(json.dumps({"topics": ["产品设计"], "source": case["product"]}, ensure_ascii=False))
    return f'''<main class="wrap study-page study-reference" data-study-page data-step-label="配图" data-event-id="{identifier}">
  <a class="study-back" href="../cases.html">← 数据产品设计库</a>
  <header class="study-header"><p class="study-product">{esc(case['product_type'])} · {esc(material_type(case))}</p><h1>{esc(case['product'])}</h1><p class="study-problem">{esc(case['user_problem'])}</p><div class="study-header-bottom"><span>{esc(case['task_type'])} · {esc(case['design_questions'][0])}</span><button class="favbtn study-save" type="button" data-fav="{identifier}" data-fav-record="{esc(json.dumps(snapshot, ensure_ascii=False))}" aria-label="收藏案例" aria-pressed="false">{bookmark_icon}<span class="sbtn-label">收藏案例</span></button></div></header>
  <nav class="study-step-nav" data-step-nav aria-label="界面与配图" hidden>{''.join(navigation)}</nav><div class="study-steps">{''.join(panels)}</div>
  <div class="study-step-controls" data-step-controls hidden><button type="button" data-step-prev>← 上一张</button><span data-step-status aria-live="polite"></span><button type="button" data-step-next>下一张 →</button></div>
  <p class="study-version">代表图优先，其余配图保留原文顺序；配图不代表一次连续操作。材料核对于 {esc(case['observed_at'])} · <a href="../e/{identifier}.html">阅读完整原文 →</a></p>
  <section class="study-lessons study-reference-details"><h2>设计拆解</h2><div>{''.join(blocks)}</div></section>
  <p class="study-limits"><b>适用边界</b>{esc(limits)}</p><nav class="study-question-links" aria-label="相关设计问题">{questions}</nav>
  <section class="study-sources"><h2>资料出处</h2><ul>{source_links}</ul><a href="../e/{identifier}.html">阅读站内原文 →</a></section>
  <section class="study-feedback content-feedback" data-content-feedback data-feedback-kind="design" data-event-id="{identifier}" data-feedback-context="{context}" aria-label="案例反馈"><h2>对你的产品设计有帮助吗？</h2><div><button type="button" data-feedback-value="useful" aria-pressed="false">有帮助</button><button type="button" data-feedback-value="not_useful" aria-pressed="false">帮助不大</button></div><p data-feedback-status aria-live="polite">反馈与收藏分开保存在当前设备。</p></section>
</main>{viewer_markup()}<script defer src="../design-studies.js"></script><script defer src="../content-feedback.js"></script>'''

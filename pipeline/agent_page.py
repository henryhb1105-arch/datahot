"""Render DataHot's Agent onboarding page and publish its public Skill bundle."""

from __future__ import annotations

import html
import shutil
from pathlib import Path


SITE_BASE = "https://henryhb1105-arch.github.io/datahot"
INSTALL_URL = f"{SITE_BASE}/datahot-skill/README.md"
SKILL_URL = f"{SITE_BASE}/datahot-skill/SKILL.md"
OPENAI_YAML_URL = f"{SITE_BASE}/datahot-skill/agents/openai.yaml"
FEED_URL = f"{SITE_BASE}/feed.xml"
INSTALL_PROMPT = f"请安装 DataHot Skill：{INSTALL_URL}"
VERIFY_PROMPT = "请用 DataHot 告诉我过去 24 小时最值得关注的 3 条数据与 AI 资讯，并附上来源链接。"


INSTALL_README = f"""# DataHot — Agent Skill

让支持 Agent Skills 的工具持续查询 DataHot 当前收录的数据与 AI 资讯。DataHot Skill 匿名、只读，不需要登录或 API Key；每次资讯请求都会重新读取官方 Atom Feed。

## 安装前审阅

- [SKILL.md]({SKILL_URL})
- [OpenAI UI metadata]({OPENAI_YAML_URL})
- [DataHot Atom Feed]({FEED_URL})

## 让当前 Agent 安装

1. 先确认当前 Agent 是否支持持久化 Agent Skills，并查阅它实际使用的 Skill 目录；不要猜测安装位置。
2. 读取上面的 `SKILL.md`，确认 Skill 名为 `datahot-news`。
3. 如果目标目录不存在同名 Skill，创建 `datahot-news/` 并保存完整的 `SKILL.md`；支持 `agents/openai.yaml` 的工具可同时保存该文件。
4. 如果已经存在同名 Skill，先向用户说明并请求是否更新，不要静默覆盖。
5. 安装后让用户新开会话，并确认 Agent 只发现一份 `datahot-news`。

如果当前 Agent 不支持持久化 Skills，读取 `SKILL.md` 后仅把它作为当前会话规则使用，并明确告诉用户“仅当前会话有效”，不要声称已经安装。

## 验证

新开会话后提问：

> {VERIFY_PROMPT}

成功答案应注明时间窗，返回当前 DataHot Feed 中的资讯，并包含 DataHot 详情链接和可用的原始信源链接。无法联网或 Feed 不可用时应明确失败，不得用模型记忆冒充实时结果。

## 更新

Skill 不会自动更新。用户明确要求更新时，重新读取本页和 `SKILL.md`，审阅变更后再替换当前 Agent 实际加载的同一份 Skill。
"""


AGENT_PAGE_CSS = """
.agent-page{max-width:820px;padding:34px 20px 72px}
.agent-hero{margin-bottom:26px}
.agent-eyebrow{margin:0 0 9px;color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
.agent-hero h1{margin:0 0 10px;font-size:29px;line-height:1.35}
.agent-hero p{max-width:680px;margin:0;color:var(--txt2);font-size:14px;line-height:1.8}
.agent-card{margin-bottom:16px;padding:20px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card)}
.agent-card h2{margin:0 0 7px;font-size:17px}
.agent-card>p{margin:0 0 15px;color:var(--sub);font-size:12.5px;line-height:1.7}
.agent-code{margin:0;padding:14px 15px;border-radius:10px;background:var(--soft);color:var(--ink);font-size:12.5px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}
.agent-actions{display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap}
.agent-copy{appearance:none;border:0;border-radius:99px;background:var(--ink);color:var(--bg);padding:9px 15px;font-size:12.5px;font-weight:700;cursor:pointer}
.agent-copy:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.agent-feedback{min-height:20px;color:var(--accent);font-size:12px}
.agent-status{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:16px}
.agent-status div{padding:11px 12px;border-radius:10px;background:var(--soft);color:var(--txt2);font-size:12px;line-height:1.65}
.agent-status b{display:block;margin-bottom:2px;color:var(--ink);font-size:12.5px}
.agent-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 16px;padding:0;list-style:none;counter-reset:agent-step}
.agent-steps li{counter-increment:agent-step;min-width:0;padding:16px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card);color:var(--txt2);font-size:12.5px;line-height:1.7}
.agent-steps li:before{content:counter(agent-step);display:grid;place-items:center;width:24px;height:24px;margin-bottom:9px;border-radius:50%;background:var(--accent-soft);color:var(--accent);font-size:12px;font-weight:800}
.agent-steps b{display:block;color:var(--ink);font-size:13px}
.agent-tech{margin-top:14px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.agent-tech summary{padding:14px 0;cursor:pointer;color:var(--ink);font-size:13px;font-weight:700}
.agent-tech-body{padding:0 0 15px;color:var(--txt2);font-size:12px;line-height:1.8}
.agent-tech-body a{color:var(--accent);overflow-wrap:anywhere}
@media(hover:hover) and (pointer:fine){.agent-copy:hover{opacity:.86}}
@media(max-width:600px){
  .agent-page{padding:24px 18px 58px}
  .agent-hero h1{font-size:25px}
  .agent-card{padding:16px}
  .agent-status,.agent-steps{grid-template-columns:1fr}
  .agent-steps{gap:9px}
}
"""


def render_agent_body() -> str:
    install_prompt = html.escape(INSTALL_PROMPT)
    verify_prompt = html.escape(VERIFY_PROMPT)
    install_url = html.escape(INSTALL_URL, quote=True)
    skill_url = html.escape(SKILL_URL, quote=True)
    feed_url = html.escape(FEED_URL, quote=True)
    return f'''<main class="wrap agent-page">
  <header class="agent-hero">
    <p class="agent-eyebrow">DataHot for Agents</p>
    <h1>让你的 Agent 读取 DataHot</h1>
    <p>复制一句话发给 Agent。支持 Skills 的工具可以跨会话使用；不支持时只在当前会话生效。</p>
  </header>

  <section class="agent-card" aria-labelledby="installTitle">
    <h2 id="installTitle">安装 DataHot Skill</h2>
    <p>安装说明会引导 Agent 先确认自己的 Skill 目录，不猜路径，也不静默覆盖已有文件。</p>
    <pre class="agent-code" id="installPrompt"><code>{install_prompt}</code></pre>
    <div class="agent-actions">
      <button class="agent-copy" type="button" data-copy-target="installPrompt">复制安装提示</button>
      <span class="agent-feedback" aria-live="polite"></span>
    </div>
    <div class="agent-status">
      <div><b>支持 Agent Skills</b>安装后新开会话，仍可调用 DataHot。</div>
      <div><b>不支持持久安装</b>Agent 应明确说明仅当前会话有效。</div>
    </div>
  </section>

  <ol class="agent-steps" aria-label="接入步骤">
    <li><b>复制</b>复制上面的安装提示。</li>
    <li><b>发送</b>发给 Agent，并确认它实际完成安装。</li>
    <li><b>验证</b>新开会话，用下面的问题检查结果。</li>
  </ol>

  <section class="agent-card" aria-labelledby="verifyTitle">
    <h2 id="verifyTitle">验证是否接入成功</h2>
    <pre class="agent-code" id="verifyPrompt"><code>{verify_prompt}</code></pre>
    <div class="agent-actions">
      <button class="agent-copy" type="button" data-copy-target="verifyPrompt">复制验证问题</button>
      <span class="agent-feedback" aria-live="polite"></span>
    </div>
  </section>

  <details class="agent-tech">
    <summary>技术信息与能力边界</summary>
    <div class="agent-tech-body">
      安装入口：<a href="{install_url}">{install_url}</a><br>
      Skill 文件：<a href="{skill_url}">{skill_url}</a><br>
      实时数据源：<a href="{feed_url}">{feed_url}</a><br>
      DataHot 通常每 6 小时更新。Skill 匿名只读，不登录、不写入、不批量转载全文；每次资讯请求重新读取 Feed。
    </div>
  </details>
</main>
<script>
(function(){{
  function fallbackCopy(text){{
    var area=document.createElement('textarea');
    area.value=text;area.setAttribute('readonly','');area.style.position='fixed';area.style.opacity='0';
    document.body.appendChild(area);area.select();
    var ok=false;try{{ok=document.execCommand('copy')}}catch(error){{ok=false}}
    area.remove();return ok;
  }}
  document.querySelectorAll('[data-copy-target]').forEach(function(button){{
    button.addEventListener('click',function(){{
      var target=document.getElementById(button.getAttribute('data-copy-target'));
      var feedback=button.parentElement.querySelector('.agent-feedback');
      var text=target?target.textContent.trim():'';
      var copied=navigator.clipboard&&window.isSecureContext
        ?navigator.clipboard.writeText(text).then(function(){{return true}},function(){{return fallbackCopy(text)}})
        :Promise.resolve(fallbackCopy(text));
      copied.then(function(ok){{
        feedback.textContent=ok?'已复制':'复制失败，请长按文字复制';
        window.setTimeout(function(){{feedback.textContent=''}},1800);
      }});
    }});
  }});
}})();
</script>'''


def publish_skill_bundle(source_dir: Path, public_dir: Path) -> None:
    """Publish the canonical Skill plus the separate Agent-facing install guide."""
    source_dir = Path(source_dir)
    public_dir = Path(public_dir)
    skill_file = source_dir / "SKILL.md"
    metadata_file = source_dir / "agents" / "openai.yaml"
    if not skill_file.is_file() or not metadata_file.is_file():
        raise FileNotFoundError("incomplete datahot-news skill bundle")
    (public_dir / "agents").mkdir(parents=True, exist_ok=True)
    (public_dir / "README.md").write_text(INSTALL_README, encoding="utf-8")
    shutil.copyfile(skill_file, public_dir / "SKILL.md")
    shutil.copyfile(metadata_file, public_dir / "agents" / "openai.yaml")

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import agent_page  # noqa: E402
import build_site  # noqa: E402


class AgentPageTests(unittest.TestCase):
    def test_install_prompt_uses_the_public_install_guide(self):
        self.assertEqual(
            agent_page.INSTALL_PROMPT,
            "请安装 DataHot Skill："
            "https://datahot.xiahongbin.com/datahot-skill/README.md",
        )
        self.assertIn(agent_page.SKILL_URL, agent_page.INSTALL_README)
        self.assertIn(agent_page.FEED_URL, agent_page.INSTALL_README)
        self.assertIn(agent_page.AGENT_FEED_URL, agent_page.INSTALL_README)
        self.assertIn(agent_page.OPENCLAW_GUIDE_URL, agent_page.INSTALL_README)
        self.assertIn("不要静默覆盖", agent_page.INSTALL_README)
        self.assertIn("仅当前会话有效", agent_page.INSTALL_README)

    def test_agent_page_has_copyable_install_and_verification_prompts(self):
        page = build_site.page_shell(
            "接入 Agent · DataHot",
            "安装 DataHot Skill",
            build_site.load_css() + agent_page.AGENT_PAGE_CSS,
            agent_page.render_agent_body(),
            build_site.tabbar("agent"),
            active="agent",
        )
        self.assertIn(agent_page.INSTALL_PROMPT, page)
        self.assertIn(agent_page.VERIFY_PROMPT, page)
        self.assertIn("复制安装提示", page)
        self.assertIn("仅当前会话有效", page)
        self.assertIn("主动推送重要资讯", page)
        self.assertIn(agent_page.OPENCLAW_GUIDE_URL, page)
        self.assertIn('data-nav-active="agent"', page)
        self.assertIn('class="mi on" href="agent.html"', page)
        self.assertIn('class="more-link on" href="agent.html"', page)

    def test_public_bundle_matches_canonical_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            public_dir = Path(directory) / "datahot-skill"
            source_dir = ROOT / "skills" / "datahot-news"
            agent_page.publish_skill_bundle(source_dir, public_dir)
            self.assertEqual(
                (public_dir / "SKILL.md").read_text(encoding="utf-8"),
                (source_dir / "SKILL.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (public_dir / "agents" / "openai.yaml").read_text(encoding="utf-8"),
                (source_dir / "agents" / "openai.yaml").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (public_dir / "README.md").read_text(encoding="utf-8"),
                agent_page.INSTALL_README,
            )
            integration_dir = ROOT / "integrations" / "openclaw"
            for name in ("README.md", "datahot_push.py", "config.example.json"):
                self.assertEqual(
                    (public_dir / "openclaw" / name).read_bytes(),
                    (integration_dir / name).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()

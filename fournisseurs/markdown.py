"""Réponses des API (Markdown) → HTML, pour l'affichage. Le HTML est ensuite nettoyé par
`agent_first.nettoyage` comme celui de Gemini ; la langue d'un bloc de code va dans
`data-langue`, comme pour Gemini."""
import re

from markdown_it import MarkdownIt

_MD = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(["table", "strikethrough"])
_LANGUE = re.compile(r'<pre><code class="language-([\w+#.-]+)">')


def markdown_vers_html(texte: str) -> str:
    return _LANGUE.sub(r'<pre data-langue="\1"><code>', _MD.render(texte))

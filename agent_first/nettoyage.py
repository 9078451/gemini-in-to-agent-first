"""Nettoyer le HTML des réponses Gemini : seules les balises de mise en forme restent."""
import nh3

BALISES = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s", "del",
    "sup", "sub", "code", "pre", "blockquote", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "a",
}
ATTRIBUTS = {"a": {"href"}, "pre": {"data-langue"}, "ol": {"start"}, "th": {"align"}, "td": {"align"}}


def nettoyer_html(html: str) -> str:
    return nh3.clean(
        html,
        tags=BALISES,
        attributes=ATTRIBUTS,
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
    )

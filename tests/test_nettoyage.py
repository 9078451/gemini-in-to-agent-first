from agent_first.nettoyage import nettoyer_html


def test_garde_la_mise_en_forme():
    html = (
        '<div class="markdown"><h2>Titre</h2><ul><li><b>gras</b> texte</li></ul>'
        "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table></div>"
    )
    assert nettoyer_html(html) == (
        "<h2>Titre</h2><ul><li><b>gras</b> texte</li></ul>"
        "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>"
    )


def test_garde_la_langue_du_code_sans_les_couleurs():
    html = '<pre data-langue="Python"><code class="code-container"><span class="hljs-string">x = 1</span></code></pre>'
    assert nettoyer_html(html) == '<pre data-langue="Python"><code>x = 1</code></pre>'


def test_retire_les_scripts():
    assert nettoyer_html("<p>a</p><script>alert(1)</script>") == "<p>a</p>"


def test_retire_les_attributs_dangereux():
    assert nettoyer_html('<p onclick="x()" style="color:red">a</p>') == "<p>a</p>"


def test_liens_ouverts_a_part():
    propre = nettoyer_html('<a href="https://exemple.fr">x</a>')
    assert 'href="https://exemple.fr"' in propre
    assert 'target="_blank"' in propre
    assert 'rel="noopener noreferrer"' in propre


def test_lien_javascript_neutralise():
    assert "javascript" not in nettoyer_html('<a href="javascript:alert(1)">x</a>')


def test_balises_inconnues_retirees_texte_garde():
    html = '<response-element><table-block><p>Texte</p></table-block></response-element><img src="x.png">'
    assert nettoyer_html(html) == "<p>Texte</p>"

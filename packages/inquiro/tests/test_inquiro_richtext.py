from inquiro.richtext import convert_rich_text


def test_html_is_sanitized_and_renders_to_each_supported_target():
    source = (
        '<script>alert("x")</script><em data-source="unsafe">Alpha &amp; Beta</em> '
        "<strong>bold</strong> X<sup>2</sup> H<sub>2</sub>O"
    )

    assert convert_rich_text(source, source="html", target="html") == (
        "<i>Alpha &amp; Beta</i> <b>bold</b> X<sup>2</sup> H<sub>2</sub>O"
    )
    assert convert_rich_text(source, source="html", target="latex") == (
        r"\textit{Alpha \& Beta} \textbf{bold} X\textsuperscript{2} H\textsubscript{2}O"
    )
    assert convert_rich_text(source, source="html", target="text") == ("Alpha & Beta bold X2 H2O")


def test_latex_aliases_and_nesting_normalize_to_safe_html():
    source = (
        r"\emph{Alpha \textbf{bold}} / \mkbibemph{Beta} / \textit{Gamma} "
        r"X\textsuperscript{2} H\textsubscript{2}O"
    )

    assert convert_rich_text(source, source="latex", target="html") == (
        "<i>Alpha <b>bold</b></i> / <i>Beta</i> / <i>Gamma</i> X<sup>2</sup> H<sub>2</sub>O"
    )


def test_latex_character_conversion_preserves_cjk_fallback():
    html = convert_rich_text(r"\emph{Garc\'{i}a 的 café}", source="latex", target="html")

    assert html == "<i>García 的 café</i>"
    encoded = convert_rich_text(html, source="html", target="latex", latex_encoding="latex")
    assert encoded.startswith(r"\textit{Garc")
    assert r"\'" in encoded
    assert "的" in encoded


def test_latex_encoding_preserves_control_word_boundaries():
    encoded = convert_rich_text(
        "física García 的 café",
        source="text",
        target="latex",
        latex_encoding="latex",
    )

    assert encoded == r"f{\'\i}sica Garc{\'\i}a 的 caf\'e"
    assert convert_rich_text(encoded, source="latex", target="text") == "física García 的 café"


def test_structural_html_degrades_to_text_separators():
    source = "<p>Hello</p><p>World</p><div>A<br>B</div><ul><li>C</li><li>D</li></ul>"

    assert convert_rich_text(source, source="html", target="text") == "Hello World A B C D"
    assert convert_rich_text(source, source="html", target="html") == "Hello World A B C D"


def test_namespaced_structural_html_preserves_text_separators():
    source = "<jats:p>First</jats:p><jats:p>Second</jats:p>"

    assert convert_rich_text(source, source="html", target="text") == "First Second"
    assert convert_rich_text(source, source="html", target="html") == "First Second"


def test_literal_angle_bracket_comparisons_survive_html_sanitizing():
    source = "Use x<y and z>w"

    assert convert_rich_text(source, source="html", target="text") == source
    assert convert_rich_text(source, source="html", target="html") == ("Use x&lt;y and z&gt;w")


def test_unknown_paired_html_wrappers_are_removed_without_losing_comparisons():
    source = "<span>Use x<y and z>w</span>"

    assert convert_rich_text(source, source="html", target="text") == "Use x<y and z>w"
    assert convert_rich_text(source, source="html", target="html") == ("Use x&lt;y and z&gt;w")


def test_unclosed_and_mismatched_inline_html_keeps_all_visible_text():
    assert convert_rich_text("<i>Title", source="html", target="html") == "<i>Title</i>"
    assert convert_rich_text("A <i>B", source="html", target="text") == "A B"
    assert (
        convert_rich_text("<b>A<i>B</b>C</i>", source="html", target="html") == "<b>A<i>B</i></b>C"
    )
    assert (
        convert_rich_text("<i>Visible<script>dropped", source="html", target="html")
        == "<i>Visible</i>"
    )


def test_inline_math_is_preserved_verbatim_across_conversions():
    assert convert_rich_text(r"$E_{mc}\in\mathbb{R}$", source="latex", target="text") == (
        r"$E_{mc}\in\mathbb{R}$"
    )
    assert convert_rich_text(r"H$_2$O", source="latex", target="html") == "H$_2$O"
    assert convert_rich_text(r"H$_2$O", source="latex", target="latex") == r"H$_2$O"


def test_web_projection_renders_inline_latex_as_safe_mathml():
    canonical = r"Energy $E_{mc}\in\mathbb{R}$ and <i>$x^2$</i>"

    rendered = convert_rich_text(canonical, source="html", target="web")

    assert rendered.count('<math xmlns="http://www.w3.org/1998/Math/MathML"') == 2
    assert "<msub>" in rendered
    assert "<msup>" in rendered
    assert "$E_" not in rendered
    assert "<i><math" in rendered
    assert convert_rich_text(canonical, source="html", target="html") == canonical


def test_web_mathml_projection_drops_active_attributes_and_falls_back_safely():
    linked = convert_rich_text(r"$\href{javascript:alert(1)}{x}$", source="html", target="web")
    malformed = convert_rich_text(
        r"$\text{&lt;/mtext&gt;&lt;script&gt;alert(1)&lt;/script&gt;}$",
        source="html",
        target="web",
    )
    invalid = convert_rich_text(r"$\frac{$", source="html", target="web")

    assert "href=" not in linked
    assert "javascript:" not in linked
    assert "<mi>x</mi>" in linked
    assert "<script>" not in malformed
    assert malformed == r"$\text{&lt;/mtext&gt;&lt;script&gt;alert(1)&lt;/script&gt;}$"
    assert invalid == r"$\frac{$"


def test_inline_math_survives_an_import_export_round_trip():
    plain = convert_rich_text("Water ($H_2O$) study", source="latex", target="text")

    assert plain == "Water ($H_2O$) study"
    assert convert_rich_text(plain, source="text", target="latex") == "Water ($H_2O$) study"


def test_currency_dollars_stay_literal_outside_math_spans():
    source = "Costs $5 and $10"

    assert convert_rich_text(source, source="text", target="latex") == r"Costs \$5 and \$10"


def test_currency_codes_do_not_form_a_false_math_span():
    source = "Costs US$5 and CA$10"

    assert convert_rich_text(source, source="text", target="latex") == (r"Costs US\$5 and CA\$10")
    assert convert_rich_text("$5 + 10$", source="text", target="latex") == "$5 + 10$"


def test_escaped_currency_dollars_decode_outside_math():
    source = r"Costs \$5 and \$10; equation $5 + 10$"

    assert convert_rich_text(source, source="latex", target="text") == (
        "Costs $5 and $10; equation $5 + 10$"
    )


def test_math_inside_markup_is_exported_without_internal_escaping():
    encoded = convert_rich_text(
        "<em>$a_b$</em> file_name.doc",
        source="html",
        target="latex",
        latex_encoding="latex",
    )

    assert encoded == r"\textit{$a_b$} file\_name.doc"

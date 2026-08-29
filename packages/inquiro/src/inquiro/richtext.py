"""Convert a deliberately small scholarly rich-text vocabulary between formats."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from typing import Literal
from xml.etree import ElementTree

from latex2mathml.converter import convert as _latex_math_to_mathml
from pylatexenc.latex2text import LatexNodes2Text  # type: ignore[import-untyped]
from pylatexenc.latexencode import (  # type: ignore[import-untyped]
    RULE_DICT,
    UnicodeToLatexConversionRule,
    UnicodeToLatexEncoder,
)

type RichTextSource = Literal["html", "latex", "text"]
type RichTextTarget = Literal["html", "latex", "text", "web"]
type LatexEncoding = Literal["unicode", "latex"]

_HTML_TAGS = {
    "em": "i",
    "i": "i",
    "strong": "b",
    "b": "b",
    "sup": "sup",
    "sub": "sub",
}
_LATEX_TAGS = {
    "emph": "i",
    "mkbibemph": "i",
    "textit": "i",
    "textbf": "b",
    "textsuperscript": "sup",
    "textsubscript": "sub",
}
_LATEX_COMMANDS = {
    "i": "textit",
    "b": "textbf",
    "sup": "textsuperscript",
    "sub": "textsubscript",
}
_DROP_CONTENT_TAGS = {"script", "style", "template"}
_HTML_SEPARATOR_TAGS = {
    "blockquote",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
}
_SINGLE_PROTECTED_CHARACTER = re.compile(r"\{([^{}])\}")
_CURRENCY_AMOUNT_START = re.compile(r"\d+(?:[.,]\d+)?")
_EXPLICIT_MATH_SYNTAX = re.compile(r"[\\_^{}=+*/<>]")
_MAX_INLINE_MATH_SPAN = 200
_MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML"
_MATHML_TAGS = {
    "math",
    "menclose",
    "mfrac",
    "mi",
    "mn",
    "mo",
    "mover",
    "mpadded",
    "mphantom",
    "mroot",
    "mrow",
    "mspace",
    "msqrt",
    "mstyle",
    "msub",
    "msubsup",
    "msup",
    "mtable",
    "mtd",
    "mtext",
    "mtr",
    "munder",
    "munderover",
}
_MATHML_ATTRIBUTES = {
    "accent",
    "accentunder",
    "columnalign",
    "columnlines",
    "columnspacing",
    "depth",
    "display",
    "displaystyle",
    "fence",
    "form",
    "height",
    "linebreak",
    "linethickness",
    "lspace",
    "mathsize",
    "mathvariant",
    "maxsize",
    "minsize",
    "movablelimits",
    "notation",
    "rowalign",
    "rowlines",
    "rowspacing",
    "rspace",
    "scriptlevel",
    "separator",
    "stretchy",
    "symmetric",
    "voffset",
    "width",
}
_LATEX_DECODER = LatexNodes2Text()
_LATEX_ENCODER = UnicodeToLatexEncoder(
    conversion_rules=[
        UnicodeToLatexConversionRule(
            RULE_DICT,
            {
                # Canonical rich text may deliberately contain BibTeX case
                # protection or a LaTeX command. Preserve that syntax while
                # still encoding ordinary Unicode and TeX-special text.
                ord("$"): "$",
                ord("\\"): "\\",
                ord("^"): "^",
                ord("{"): "{",
                ord("}"): "}",
            },
        ),
        "defaults",
    ],
    unknown_char_policy="keep",
    unknown_char_warning=False,
)
_UNICODE_LATEX_ENCODER = UnicodeToLatexEncoder(
    conversion_rules=[
        UnicodeToLatexConversionRule(
            RULE_DICT,
            {
                ord("#"): r"\#",
                ord("%"): r"\%",
                ord("&"): r"\&",
                ord("_"): r"\_",
                ord("~"): r"\textasciitilde{}",
            },
        )
    ],
    replacement_latex_protection="none",
    unknown_char_policy="keep",
    unknown_char_warning=False,
)
ElementTree.register_namespace("", _MATHML_NAMESPACE)


def _compact(value: str) -> str:
    return " ".join(value.split())


def _local_html_tag(tag: str) -> str:
    return tag.rsplit(":", 1)[-1].casefold()


@dataclass(frozen=True)
class _Tag:
    """One styled span in the canonical i/b/sup/sub vocabulary."""

    kind: str
    child: _Node


type _NodeChild = str | _Tag
type _Node = _NodeChild | _Tuple


@dataclass
class _Builder:
    parts: list[_Node] = field(default_factory=list)

    def text(self, value: str) -> None:
        if value:
            self.parts.append(value)

    def tag(self, kind: str, parts: list[_Node]) -> None:
        if parts:
            self.parts.append(_Tag(kind, _Text(tuple(parts)).root()))

    def render(self, parts: list[_NodeChild] | None = None) -> _Node:
        merged: list[str | _Tag] = []
        for node in self.parts if parts is None else parts:
            if isinstance(node, str) and merged and isinstance(merged[-1], str):
                merged[-1] += node
            else:
                merged.append(node)  # type: ignore[arg-type]
        if not merged:
            return ""
        if len(merged) == 1:
            return merged[0]
        return _Tuple(tuple(merged))


@dataclass(frozen=True)
class _Text:
    """An ordered sequence of canonical rich-text nodes."""

    nodes: tuple[_Node, ...]

    def root(self) -> _Node:
        if not self.nodes:
            return ""
        if len(self.nodes) == 1:
            return self.nodes[0]
        return _Tuple(self.nodes)


@dataclass(frozen=True)
class _Tuple:
    children: tuple[_Node, ...]


def _iter_nodes(node: _Node) -> tuple[_NodeChild, ...]:
    if isinstance(node, _Tuple):
        flattened: list[_NodeChild] = []
        for child in node.children:
            flattened.extend(_iter_nodes(child))
        return tuple(flattened)
    if isinstance(node, _Tag):
        return (node,)
    return (node,)


def _render_html(node: _Node) -> str:
    chunks: list[str] = []
    for child in _iter_nodes(node):
        if isinstance(child, str):
            chunks.append(escape(child, quote=False))
        else:
            chunks.append(f"<{child.kind}>{_render_html(child.child)}</{child.kind}>")
    return "".join(chunks)


def _render_web(node: _Node) -> str:
    chunks: list[str] = []
    for child in _iter_nodes(node):
        if isinstance(child, str):
            chunks.extend(
                _render_mathml(segment) if is_math else escape(segment, quote=False)
                for segment, is_math in _math_segments(child)
            )
        else:
            chunks.append(f"<{child.kind}>{_render_web(child.child)}</{child.kind}>")
    return "".join(chunks)


def _render_mathml(span: str) -> str:
    """Render one ``$...$`` span through a strict, inert MathML projection."""
    try:
        root = ElementTree.fromstring(_latex_math_to_mathml(span[1:-1]))
    except Exception:
        return escape(span, quote=False)
    for element in root.iter():
        namespace, separator, local_name = element.tag.removeprefix("{").partition("}")
        if separator != "}" or namespace != _MATHML_NAMESPACE or local_name not in _MATHML_TAGS:
            return escape(span, quote=False)
        element.attrib = {
            name: value for name, value in element.attrib.items() if name in _MATHML_ATTRIBUTES
        }
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


def _render_text(node: _Node) -> str:
    chunks: list[str] = []
    for child in _iter_nodes(node):
        if isinstance(child, str):
            chunks.append(child)
        else:
            chunks.append(_render_text(child.child))
    return "".join(chunks)


def _decode_latex_text(value: str) -> str:
    if not value:
        return ""
    if "\\" not in value:
        return value
    try:
        decoded = _LATEX_DECODER.latex_to_text(value)
    except (IndexError, TypeError, ValueError):
        decoded = value
    decoded = decoded.replace(r"\$", "$")
    return _SINGLE_PROTECTED_CHARACTER.sub(r"\1", decoded)


def _encode_unicode_latex(value: str) -> str:
    return _UNICODE_LATEX_ENCODER.unicode_to_latex(value)


def _encode_pure_latex(value: str) -> str:
    return _LATEX_ENCODER.unicode_to_latex(value)


def _render_latex(node: _Node, encoding: LatexEncoding) -> str:
    chunks: list[str] = []
    for child in _iter_nodes(node):
        if isinstance(child, str):
            chunks.append(_render_latex_text(child, encoding))
        else:
            command = _LATEX_COMMANDS[child.kind]
            body = _render_latex(child.child, encoding)
            chunks.append(f"\\{command}{{{body}}}" if body else "")
    return "".join(chunks)


def _render_latex_text(value: str, encoding: LatexEncoding) -> str:
    # Inline math spans are preserved verbatim: neither their commands nor
    # their _^ markers may pass through TeX encoding, or a later export
    # would re-encode the broken result. Outside math, currency dollars are
    # escaped after encoding; math detection runs on the raw value so TeX
    # escapes inside a span (e.g. \{) never split it.
    return "".join(
        segment if is_math else _encode_latex_segment(segment, encoding)
        for segment, is_math in _math_segments(value)
    )


def _encode_latex_segment(value: str, encoding: LatexEncoding) -> str:
    encoded = _encode_pure_latex(value) if encoding == "latex" else _encode_unicode_latex(value)
    return encoded.replace("$", r"\$")


def _math_span_end(value: str, open_index: int) -> int | None:
    """Return the index just past the closing $ of a sane inline math span.

    Sanity rules keep currency dollars out: the opener abuts content on its
    right, the closer abuts content on its left, escaped dollars never count
    as delimiters, and the span stays short.
    """
    start = open_index + 1
    if start >= len(value) or value[start].isspace():
        return None
    position = start
    while position < len(value):
        character = value[position]
        if character == "\\":
            position += 2
            continue
        if character == "$":
            if 0 < position - start <= _MAX_INLINE_MATH_SPAN and not value[position - 1].isspace():
                content = value[start:position]
                amount = _CURRENCY_AMOUNT_START.match(content)
                remainder = content[amount.end() :] if amount else ""
                if (
                    amount
                    and any(character.isalpha() for character in remainder)
                    and any(character.isspace() for character in remainder)
                    and not _EXPLICIT_MATH_SYNTAX.search(content)
                ):
                    # In prose such as ``US$5 and CA$10``, the second currency
                    # marker can otherwise look like the closer for the first.
                    return None
                return position + 1
            return None
        position += 1
    return None


def _math_segments(value: str) -> list[tuple[str, bool]]:
    """Split a string into (segment, is_math) runs across paired $...$ spans."""
    segments: list[tuple[str, bool]] = []
    text_start = 0
    position = 0
    while position < len(value):
        character = value[position]
        if character == "\\":
            position += 2
            continue
        if character == "$":
            span_end = _math_span_end(value, position)
            if span_end is not None:
                if position > text_start:
                    segments.append((value[text_start:position], False))
                segments.append((value[position:span_end], True))
                position = text_start = span_end
                continue
        position += 1
    if text_start < len(value):
        segments.append((value[text_start:], False))
    return segments


class _HTMLRichTextParser(HTMLParser):
    """Parse HTML into canonical rich text, keeping stray ``<`` as literal text.

    ``html.parser`` swallows comparison operators such as ``x<y and z>w`` as
    pseudo-tags (tag name ``y`` with junk attributes). Any start tag whose
    raw text is not a plain ``<name>``/``</name>`` token is treated as data.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._root = _Builder()
        self._stack: list[tuple[str, str | None, _Builder]] = []
        self._dropped_depth = 0

    def _append_separator(self) -> None:
        builder = self._stack[-1][2] if self._stack else self._root
        parts = builder.parts
        if parts and (not isinstance(parts[-1], str) or not parts[-1].endswith((" ", "\n", "\t"))):
            parts.append(" ")

    def _is_pseudo_tag(self) -> bool:
        raw = self.get_starttag_text()
        if raw is None:
            return False
        inner = raw.strip()
        inner = inner[1:-1].rstrip("/") if inner.endswith(">") else inner[1:]
        parts = inner.split(None, 1)
        if len(parts) < 2:
            return False
        # Real attributes either carry '=' or stand alone (boolean attrs).
        # Two consecutive valueless tokens, as in ``<y and z>``, mean the
        # parser swallowed a comparison operator as a tag.
        valueless_run = False
        for token in parts[1].split():
            if "=" in token:
                valueless_run = False
            elif valueless_run:
                return True
            else:
                valueless_run = True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._is_pseudo_tag():
            (self._stack[-1][2] if self._stack else self._root).text(
                self.get_starttag_text() or f"<{tag}>"
            )
            return
        del attrs
        normalized = _local_html_tag(tag)
        if self._dropped_depth:
            if normalized in _DROP_CONTENT_TAGS:
                self._dropped_depth += 1
            return
        if normalized in _DROP_CONTENT_TAGS:
            self._dropped_depth = 1
        elif normalized in _HTML_TAGS:
            self._stack.append((normalized, _HTML_TAGS[normalized], _Builder()))
        elif normalized in _HTML_SEPARATOR_TAGS:
            self._append_separator()
        else:
            self._stack.append((normalized, None, _Builder()))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def _close_top(self) -> None:
        _source_tag, canonical, builder = self._stack.pop()
        parent = self._stack[-1][2] if self._stack else self._root
        if canonical is None:
            # Unknown tags are dropped; their children flow into the parent.
            parent.parts.extend(builder.parts)
        else:
            parent.tag(canonical, builder.parts)

    def handle_endtag(self, tag: str) -> None:
        normalized = _local_html_tag(tag)
        if self._dropped_depth:
            if normalized in _DROP_CONTENT_TAGS:
                self._dropped_depth -= 1
            return
        matching_index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index][0] == normalized
            ),
            None,
        )
        if matching_index is None:
            if normalized in _HTML_SEPARATOR_TAGS:
                self._append_separator()
            return
        # HTMLParser accepts crossed/mismatched markup. Close descendants first
        # so their visible content is not discarded with the matching ancestor.
        while len(self._stack) > matching_index:
            self._close_top()

    def handle_data(self, data: str) -> None:
        if not self._dropped_depth and data:
            (self._stack[-1][2] if self._stack else self._root).text(data)

    def rich_text(self) -> _Node:
        # ``HTMLParser.close()`` does not emit end-tag callbacks for open
        # elements. Fold every remaining builder into its parent at EOF.
        while self._stack:
            self._close_top()
        return self._root.render()


def _parse_html(value: str) -> _Node:
    parser = _HTMLRichTextParser()
    parser.feed(value.strip())
    parser.close()
    return parser.rich_text()


class _LaTeXRichTextParser:
    def __init__(self, value: str) -> None:
        self.value = _compact(value)
        self.position = 0

    def parse(self, *, grouped: bool = False) -> _Node:
        parts: list[_NodeChild] = []
        plain: list[str] = []

        def flush() -> None:
            if plain:
                parts.append(_decode_latex_text("".join(plain)))
                plain.clear()

        while self.position < len(self.value):
            character = self.value[self.position]
            if character == "}" and grouped:
                self.position += 1
                break
            if character == "{":
                flush()
                self.position += 1
                inner = self.parse(grouped=True)
                for child in _iter_nodes(inner):
                    if isinstance(child, str):
                        parts.append(child)
                    else:
                        parts.append(child)
                continue
            if character == "$":
                span_end = _math_span_end(self.value, self.position)
                if span_end is not None:
                    # Inline math is preserved verbatim: neither its commands
                    # nor its _^ markers may pass through TeX decoding, or a
                    # later export would re-encode the broken result.
                    flush()
                    parts.append(self.value[self.position : span_end])
                    self.position = span_end
                    continue
                plain.append(character)
                self.position += 1
                continue
            if character != "\\":
                plain.append(character)
                self.position += 1
                continue

            command_start = self.position
            self.position += 1
            if self.position >= len(self.value):
                plain.append("\\")
                break
            if not self.value[self.position].isalpha():
                self.position += 1
                if self.position < len(self.value) and self.value[self.position] == "{":
                    depth = 0
                    while self.position < len(self.value):
                        current = self.value[self.position]
                        self.position += 1
                        depth += current == "{"
                        depth -= current == "}"
                        if depth == 0:
                            break
                plain.append(self.value[command_start : self.position])
                continue

            while self.position < len(self.value) and self.value[self.position].isalpha():
                self.position += 1
            command = self.value[command_start + 1 : self.position]
            argument_start = self.position
            while argument_start < len(self.value) and self.value[argument_start].isspace():
                argument_start += 1
            if argument_start < len(self.value) and self.value[argument_start] == "{":
                self.position = argument_start + 1
                argument = self.parse(grouped=True)
                flush()
                tag = _LATEX_TAGS.get(command)
                if tag:
                    parts.append(_Tag(tag, argument))
                else:
                    parts.extend(_iter_nodes(argument))
                continue
            plain.append(self.value[command_start : self.position])

        flush()
        return _Text(tuple(parts)).root()


def _parse_latex(value: str) -> _Node:
    return _LaTeXRichTextParser(value).parse()


def convert_rich_text(
    value: str | None,
    *,
    source: RichTextSource,
    target: RichTextTarget,
    latex_encoding: LatexEncoding = "unicode",
) -> str:
    """Convert supported inline markup, sanitizing HTML and degrading unknown LaTeX to text."""
    if not value:
        return ""
    if source == "html":
        rich_text = _parse_html(value)
    elif source == "latex":
        rich_text = _parse_latex(value)
    elif source == "text":
        rich_text = _compact(value)
    else:
        raise ValueError("rich-text source must be html, latex or text")

    if target == "html":
        return _render_html(rich_text).strip()
    if target == "web":
        return _render_web(rich_text).strip()
    if target == "text":
        return _render_text(rich_text).strip()
    if target == "latex":
        return _render_latex(rich_text, latex_encoding).strip()
    raise ValueError("rich-text target must be html, latex, text or web")


__all__ = ["convert_rich_text"]

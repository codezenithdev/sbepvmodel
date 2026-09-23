"""Typeset inline equation notation into sub/superscript runs.

Report equations are authored with a compact ASCII convention: ``_`` marks a
subscript and ``^`` a superscript, whose body is either a parenthesised group
(``^(t-1)``) or a run of alphanumerics and commas (``R_sh``, ``E_j,1``,
``x^2``). This module parses that convention into a small node tree and renders
it three ways -- ReportLab intra-paragraph markup, python-docx run segments,
and a plain-text fallback used for column-width measurement. Only content the
report explicitly marks as an equation is parsed, so hashes and version strings
in other monospaced columns keep their literal underscores.
"""

from xml.sax.saxutils import escape

_SUBSCRIPT_BODY = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789,")
_SUPERSCRIPT_BODY = _SUBSCRIPT_BODY | set("+-")


def _parse(source, index=0, stop=None):
    """Return (nodes, next_index). Nodes are str, ('sup', nodes) or ('sub', nodes)."""
    nodes, buffer = [], ""
    while index < len(source):
        char = source[index]
        if stop is not None and char == stop:
            break
        if char in "_^" and index + 1 < len(source):
            following = source[index + 1]
            if following == "(":
                inner, closing = _parse(source, index + 2, stop=")")
                index = closing + 1 if closing < len(source) else closing
            else:
                allowed = _SUPERSCRIPT_BODY if char == "^" else _SUBSCRIPT_BODY
                end = index + 1
                while end < len(source) and source[end] in allowed:
                    end += 1
                if end == index + 1:  # nothing to raise or lower; keep literal
                    buffer += char
                    index += 1
                    continue
                inner = [source[index + 1:end]]
                index = end
            if buffer:
                nodes.append(buffer)
                buffer = ""
            nodes.append(("sup" if char == "^" else "sub", inner))
            continue
        buffer += char
        index += 1
    if buffer:
        nodes.append(buffer)
    return nodes, index


def _nodes(source):
    return _parse(str(source))[0]


def _to_markup(nodes):
    pieces = []
    for node in nodes:
        if isinstance(node, str):
            pieces.append(escape(node).replace("\n", "<br/>"))
        else:
            tag = "super" if node[0] == "sup" else "sub"
            pieces.append(f"<{tag}>{_to_markup(node[1])}</{tag}>")
    return "".join(pieces)


def _to_plain(nodes):
    pieces = []
    for node in nodes:
        pieces.append(node if isinstance(node, str) else _to_plain(node[1]))
    return "".join(pieces)


def _to_runs(nodes, script=None, out=None):
    if out is None:
        out = []
    for node in nodes:
        if isinstance(node, str):
            out.append((node, script))
        else:
            _to_runs(node[1], "super" if node[0] == "sup" else "sub", out)
    return out


def equation_markup(source):
    """ReportLab markup with ``<super>``/``<sub>`` tags; newlines become ``<br/>``."""
    return _to_markup(_nodes(source))


def equation_plain(source):
    """Visible characters with the raise/lower markers removed (for measurement)."""
    return _to_plain(_nodes(source))


def equation_runs(source):
    """List of ``(text, script)`` where script is None, ``'super'`` or ``'sub'``.

    Runs preserve embedded newlines inside their text so callers can split them
    into separate lines when a target (like a Word cell) needs explicit breaks.
    """
    return _to_runs(_nodes(source))

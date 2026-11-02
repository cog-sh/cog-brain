"""One round-trip YAML parser for human-authored notes and every consumer."""
from __future__ import annotations

import io
import re
from collections.abc import Mapping

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString


def split(raw: str) -> tuple[str, str]:
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", raw, re.S)
    if raw.startswith("---") and not match:
        raise ValueError("invalid or unclosed YAML frontmatter")
    return (match.group(1) + "\n", raw[match.end():]) if match else ("", raw)


def parser() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.allow_duplicate_keys = False
    return yaml


def parse(block: str) -> CommentedMap:
    value = parser().load(block) if block.strip() else CommentedMap()
    if value is None:
        return CommentedMap()
    if not isinstance(value, Mapping):
        raise ValueError("frontmatter must be a YAML mapping")
    return value


def sequence(values) -> CommentedSeq:
    # quote each item: `superseded_by: [["[[X]]"]]` would otherwise be written as
    # `[[[X]]]`, which YAML still reads back but the link regex reads as `[X` —
    # the edge vanished from backlinks/graph and appeared as a phantom in broken_links.
    seq = CommentedSeq(DoubleQuotedScalarString(str(v)) for v in values)
    seq.fa.set_flow_style()
    return seq


def dump(fields: Mapping) -> str:
    fields = fields if isinstance(fields, CommentedMap) else CommentedMap(fields)
    for key, value in list(fields.items()):
        if isinstance(value, list) and not isinstance(value, CommentedSeq):
            fields[key] = sequence(value)
    stream = io.StringIO()
    parser().dump(fields, stream)
    return "---\n" + stream.getvalue() + "---"


def render(fields: Mapping, body: str) -> str:
    return dump(fields) + "\n" + body

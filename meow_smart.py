import ast
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SmartPlaylist:
    key: str
    label: str
    description: str
    indices: tuple


@dataclass(frozen=True)
class CustomSmartMix:
    key: str
    label: str
    description: str
    rule: str
    sort: str
    limit: int | None
    expression: object


class SmartRuleError(ValueError):
    pass


_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<op>>=|<=|!=|==|!~|=|~|>|<)
        |(?P<lparen>\()
        |(?P<rparen>\))
        |(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
        |(?P<number>-?\d+(?:\.\d+)?)
        |(?P<ident>[A-Za-z_][A-Za-z0-9_.-]*)
    )""",
    re.VERBOSE,
)

_FIELD_ALIASES = {
    "plays": "play_count",
    "pawmarked": "favorite",
    "favourite": "favorite",
}

_TEXT_FIELDS = {
    "title",
    "artist",
    "album",
    "album_artist",
    "genre",
    "year",
    "filename",
    "folder",
}
_NUMBER_FIELDS = {
    "duration",
    "play_count",
    "last_played_ns",
    "added_at_ns",
}
_BOOL_FIELDS = {
    "favorite",
    "played",
    "tagged",
}
_ALLOWED_FIELDS = _TEXT_FIELDS | _NUMBER_FIELDS | _BOOL_FIELDS


def _slug(value):
    text = re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
    return text or "mix"


def _stats_for(metadata, stats_by_path, index):
    path = str(metadata[index].path.resolve())
    return stats_by_path.get(
        path,
        {
            "favorite": False,
            "play_count": 0,
            "last_played_ns": None,
            "added_at_ns": 0,
        },
    )


def _tokenize(rule):
    tokens = []
    position = 0
    text = str(rule)

    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if match is None:
            remainder = text[position:].strip()
            if not remainder:
                break
            raise SmartRuleError(
                f"Unexpected token near {text[position:position + 20]!r}"
            )

        position = match.end()
        kind = match.lastgroup
        value = match.group(kind)

        if kind == "ident":
            lowered = value.casefold()
            if lowered in {"and", "or", "not"}:
                tokens.append((lowered, lowered))
            elif lowered in {"true", "false"}:
                tokens.append(("bool", lowered == "true"))
            else:
                tokens.append(("ident", value))
        elif kind == "string":
            try:
                tokens.append(("value", ast.literal_eval(value)))
            except (SyntaxError, ValueError) as exc:
                raise SmartRuleError("Invalid quoted string") from exc
        elif kind == "number":
            number = float(value) if "." in value else int(value)
            tokens.append(("value", number))
        elif kind == "op":
            tokens.append(("op", value))
        else:
            tokens.append((kind, value))

    return tokens


class _RuleParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def peek(self, kind=None):
        if self.position >= len(self.tokens):
            return None
        token = self.tokens[self.position]
        if kind is not None and token[0] != kind:
            return None
        return token

    def pop(self, kind=None):
        token = self.peek()
        if token is None:
            raise SmartRuleError("Unexpected end of rule")
        if kind is not None and token[0] != kind:
            raise SmartRuleError(
                f"Expected {kind}, found {token[1]!r}"
            )
        self.position += 1
        return token

    def parse(self):
        if not self.tokens:
            raise SmartRuleError("Rule is empty")
        expression = self.parse_or()
        if self.peek() is not None:
            raise SmartRuleError(
                f"Unexpected token {self.peek()[1]!r}"
            )
        return expression

    def parse_or(self):
        node = self.parse_and()
        while self.peek("or"):
            self.pop("or")
            node = ("or", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.peek("and"):
            self.pop("and")
            node = ("and", node, self.parse_not())
        return node

    def parse_not(self):
        if self.peek("not"):
            self.pop("not")
            return ("not", self.parse_not())
        return self.parse_primary()

    def parse_primary(self):
        if self.peek("lparen"):
            self.pop("lparen")
            node = self.parse_or()
            self.pop("rparen")
            return node
        return self.parse_comparison()

    def parse_comparison(self):
        field = self.pop("ident")[1].casefold()
        field = _FIELD_ALIASES.get(field, field)
        if field not in _ALLOWED_FIELDS:
            raise SmartRuleError(f"Unknown field: {field}")

        operator = self.pop("op")[1]
        token = self.pop()

        if token[0] in {"value", "bool"}:
            value = token[1]
        elif token[0] == "ident":
            value = token[1]
        else:
            raise SmartRuleError(
                f"Expected a value after {operator}"
            )

        return ("compare", field, operator, value)


def compile_rule(rule):
    return _RuleParser(_tokenize(rule)).parse()


def _field_value(metadata, stats_by_path, index, field):
    meta = metadata[index]
    stats = _stats_for(metadata, stats_by_path, index)

    if field == "favorite":
        return bool(stats["favorite"])
    if field == "played":
        return int(stats["play_count"]) > 0
    if field == "play_count":
        return int(stats["play_count"])
    if field == "last_played_ns":
        return int(stats["last_played_ns"] or 0)
    if field == "added_at_ns":
        return int(stats["added_at_ns"] or 0)
    if field == "tagged":
        return bool(getattr(meta, "tagged", False))
    if field == "duration":
        return float(getattr(meta, "duration", 0.0) or 0.0)

    return getattr(meta, field, "") or ""


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).casefold()
    if text in {"true", "yes", "1", "on"}:
        return True
    if text in {"false", "no", "0", "off"}:
        return False
    raise SmartRuleError(f"Expected boolean, got {value!r}")


def _compare(lhs, operator, rhs, field):
    if operator in {"~", "!~"}:
        matched = str(rhs).casefold() in str(lhs).casefold()
        return matched if operator == "~" else not matched

    if field in _BOOL_FIELDS:
        left = bool(lhs)
        right = _coerce_bool(rhs)
    elif field in _NUMBER_FIELDS or (
        field == "year" and operator in {">", ">=", "<", "<="}
    ):
        try:
            left = float(lhs or 0)
            right = float(rhs)
        except (TypeError, ValueError) as exc:
            raise SmartRuleError(
                f"{field} requires a numeric comparison value"
            ) from exc
    else:
        left = str(lhs).casefold()
        right = str(rhs).casefold()

    if operator in {"=", "=="}:
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right

    raise SmartRuleError(f"Unsupported operator: {operator}")


def rule_matches(expression, metadata, stats_by_path, index):
    kind = expression[0]

    if kind == "and":
        return (
            rule_matches(expression[1], metadata, stats_by_path, index)
            and rule_matches(expression[2], metadata, stats_by_path, index)
        )
    if kind == "or":
        return (
            rule_matches(expression[1], metadata, stats_by_path, index)
            or rule_matches(expression[2], metadata, stats_by_path, index)
        )
    if kind == "not":
        return not rule_matches(
            expression[1],
            metadata,
            stats_by_path,
            index,
        )

    _, field, operator, rhs = expression
    lhs = _field_value(
        metadata,
        stats_by_path,
        index,
        field,
    )
    return _compare(lhs, operator, rhs, field)


def _sort_value(metadata, stats_by_path, index, field):
    field = _FIELD_ALIASES.get(field.casefold(), field.casefold())
    if field not in _ALLOWED_FIELDS:
        field = "artist"

    value = _field_value(metadata, stats_by_path, index, field)
    if isinstance(value, str):
        return value.casefold()
    return value


def load_custom_mix_definitions(path):
    path = getattr(path, "expanduser", lambda: path)()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], []
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"Could not read custom Smart Mixes: {exc}"]

    if isinstance(payload, dict):
        payload = payload.get("mixes", [])

    if not isinstance(payload, list):
        return [], ["Custom Smart Mix file must contain a list or {mixes: [...]}"]

    definitions = []
    errors = []
    used_keys = set()

    for position, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            errors.append(f"Mix #{position} is not an object")
            continue

        label = str(item.get("name", "")).strip()
        rule = str(item.get("rule", "")).strip()

        if not label or not rule:
            errors.append(
                f"Mix #{position} needs both name and rule"
            )
            continue

        try:
            expression = compile_rule(rule)
        except SmartRuleError as exc:
            errors.append(f"{label}: {exc}")
            continue

        key_base = f"custom:{_slug(label)}"
        key = key_base
        suffix = 2
        while key in used_keys:
            key = f"{key_base}-{suffix}"
            suffix += 1
        used_keys.add(key)

        sort = str(item.get("sort", "artist")).strip() or "artist"

        raw_limit = item.get("limit")
        if raw_limit is None:
            limit = None
        else:
            try:
                limit = max(1, min(10000, int(raw_limit)))
            except (TypeError, ValueError):
                errors.append(f"{label}: limit must be an integer")
                continue

        definitions.append(
            CustomSmartMix(
                key=key,
                label=label,
                description=str(
                    item.get(
                        "description",
                        f"Custom rule: {rule}",
                    )
                ).strip(),
                rule=rule,
                sort=sort,
                limit=limit,
                expression=expression,
            )
        )

    return definitions, errors


def _build_custom_playlist(
    definition,
    metadata,
    stats_by_path,
):
    indices = [
        index
        for index in range(len(metadata))
        if rule_matches(
            definition.expression,
            metadata,
            stats_by_path,
            index,
        )
    ]

    sort_field = definition.sort
    reverse = sort_field.startswith("-")
    if reverse:
        sort_field = sort_field[1:]

    indices.sort(
        key=lambda index: (
            _sort_value(
                metadata,
                stats_by_path,
                index,
                sort_field,
            ),
            metadata[index].title.casefold(),
        ),
        reverse=reverse,
    )

    if definition.limit is not None:
        indices = indices[:definition.limit]

    return SmartPlaylist(
        definition.key,
        definition.label,
        definition.description,
        tuple(indices),
    )


def build_smart_playlists(
    metadata,
    stats_by_path,
    custom_definitions=None,
):
    indices = list(range(len(metadata)))

    pawmarked = [
        index
        for index in indices
        if _stats_for(metadata, stats_by_path, index)["favorite"]
    ]

    recent = sorted(
        (
            index
            for index in indices
            if _stats_for(metadata, stats_by_path, index)["last_played_ns"]
            is not None
        ),
        key=lambda index: (
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["last_played_ns"]
                or 0
            ),
            metadata[index].title.casefold(),
        ),
    )

    most_played = sorted(
        (
            index
            for index in indices
            if int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["play_count"]
            )
            > 0
        ),
        key=lambda index: (
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["play_count"]
            ),
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["last_played_ns"]
                or 0
            ),
            metadata[index].title.casefold(),
        ),
    )

    fresh = sorted(
        indices,
        key=lambda index: (
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["added_at_ns"]
                or 0
            ),
            metadata[index].title.casefold(),
        ),
    )[:100]

    unplayed = sorted(
        (
            index
            for index in indices
            if int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["play_count"]
            )
            == 0
        ),
        key=lambda index: (
            metadata[index].artist.casefold(),
            metadata[index].album.casefold(),
            metadata[index].track_number or 999999,
            metadata[index].title.casefold(),
        ),
    )

    playlists = [
        SmartPlaylist(
            "pawmarked",
            "Pawmarked Mix",
            "Every track carrying your Pawmark.",
            tuple(pawmarked),
        ),
        SmartPlaylist(
            "recent",
            "Recently Purrred",
            "Tracks ordered by the last time you played them.",
            tuple(recent),
        ),
        SmartPlaylist(
            "most-played",
            "Most Purrred",
            "Your most frequently played tracks.",
            tuple(most_played),
        ),
        SmartPlaylist(
            "fresh",
            "Fresh Finds",
            "The newest tracks known to the Cat Catalog.",
            tuple(fresh),
        ),
        SmartPlaylist(
            "unplayed",
            "Never Purrred",
            "Tracks with a play count of zero.",
            tuple(unplayed),
        ),
    ]

    for definition in custom_definitions or ():
        playlists.append(
            _build_custom_playlist(
                definition,
                metadata,
                stats_by_path,
            )
        )

    genres = {}
    for index, meta in enumerate(metadata):
        genre = (meta.genre or "").strip()
        if not genre:
            continue
        genres.setdefault(genre, []).append(index)

    for genre in sorted(genres, key=str.casefold):
        genre_indices = sorted(
            genres[genre],
            key=lambda index: (
                metadata[index].artist.casefold(),
                metadata[index].album.casefold(),
                metadata[index].track_number or 999999,
                metadata[index].title.casefold(),
            ),
        )
        playlists.append(
            SmartPlaylist(
                f"genre:{genre}",
                f"Genre Mix · {genre}",
                f"Every track tagged as {genre}.",
                tuple(genre_indices),
            )
        )

    return playlists

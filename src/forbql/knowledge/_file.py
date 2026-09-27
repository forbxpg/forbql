"""The knowledge file: glossary terms and examples the operator keeps in git."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from forbql.policy import read_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable


class KnowledgeError(ValueError):
    """The knowledge file cannot be read, is not valid YAML, or breaks its schema."""


class _Entry(BaseModel):
    """Immutable, and an unknown key is an error rather than a silent no-op."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    @property
    def body_hash(self) -> str:
        """Hash of every field, to write and embed again only what changed.

        Returns:
            str - Hex SHA-256.

        """
        canonical = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


class GlossaryTerm(_Entry):
    """A word of the business and what it means in the data.

    Attributes:
        term: str - The word, unique in the file.
        definition: str - What it means.
        table: str | None - The table `sql` reads; with `sql` or not at all.
        sql: str | None - One expression over `table`: a condition or a measure.

    """

    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    table: str | None = Field(default=None, min_length=1)
    sql: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_pair(self) -> Self:
        """Keep `table` and `sql` together: an expression reads one named table.

        Returns:
            Self - The validated term.

        Raises:
            ValueError: If only one of them is given.

        """
        if (self.table is None) != (self.sql is None):
            msg = "table and sql go together"
            raise ValueError(msg)
        return self

    @property
    def key(self) -> str:
        """The term, which names the entry."""
        return self.term

    @property
    def body(self) -> str:
        """What search matches: the term and its definition."""
        return f"{self.term}: {self.definition}"

    @property
    def text(self) -> str:
        """Everything the entry shows a caller, for the check of names it mentions."""
        return "\n".join(part for part in (self.body, self.sql) if part)


class Example(_Entry):
    """A question and the query that answers it.

    Attributes:
        question: str - The question, unique in the file.
        sql: str - A full query.

    """

    question: str = Field(min_length=1)
    sql: str = Field(min_length=1)

    @property
    def key(self) -> str:
        """The question, which names the entry."""
        return self.question

    @property
    def body(self) -> str:
        """What search matches: the question."""
        return self.question

    @property
    def text(self) -> str:
        """Everything the entry shows a caller, for the check of names it mentions."""
        return f"{self.question}\n{self.sql}"


class KnowledgeFile(_Entry):
    """What `knowledge.yaml` holds for one connection.

    Attributes:
        glossary: tuple[GlossaryTerm, ...] - Terms.
        examples: tuple[Example, ...] - Examples, approved by being in the file.

    """

    glossary: tuple[GlossaryTerm, ...] = ()
    examples: tuple[Example, ...] = ()

    @model_validator(mode="after")
    def _check_unique(self) -> Self:
        """Refuse a term or question that repeats: the second would replace the first.

        Returns:
            Self - The validated file.

        Raises:
            ValueError: If a term or question appears twice.

        """
        for kind, keys in (
            ("term", (entry.key for entry in self.glossary)),
            ("question", (entry.key for entry in self.examples)),
        ):
            if repeated := _repeated(keys):
                msg = f"{kind} appears more than once: {', '.join(repeated)}"
                raise ValueError(msg)
        return self


def parse_knowledge(text: str, *, source: str = "<knowledge>") -> KnowledgeFile:
    """Parse and validate a knowledge file from YAML text.

    Args:
        text: str - YAML text.
        source: str - Where the text came from, used in error messages.

    Returns:
        KnowledgeFile - The validated file.

    Raises:
        KnowledgeError: If the text is not valid YAML or breaks the schema.

    """
    try:
        data = read_yaml(text)
    except yaml.YAMLError as error:
        msg = f"{source}: invalid YAML: {error}"
        raise KnowledgeError(msg) from error
    try:
        return KnowledgeFile.model_validate(data or {})
    except ValidationError as error:
        problems = "\n".join(
            f"  {'.'.join(map(str, item['loc'])) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        msg = f"{source}: invalid knowledge file:\n{problems}"
        raise KnowledgeError(msg) from error


def load_knowledge(path: str | Path) -> KnowledgeFile:
    """Read and validate a knowledge file.

    Args:
        path: str | Path - Path to the YAML file.

    Returns:
        KnowledgeFile - The validated file.

    Raises:
        KnowledgeError: If the file cannot be read or does not hold a valid one.

    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        msg = f"{path}: cannot read: {error.strerror}"
        raise KnowledgeError(msg) from error
    return parse_knowledge(text, source=str(path))


def _repeated(keys: Iterable[str]) -> list[str]:
    """Find keys that appear more than once, ignoring case.

    Args:
        keys: Iterable[str] - The keys.

    Returns:
        list[str] - The repeated ones, as first written.

    """
    seen: dict[str, str] = {}
    repeated: list[str] = []
    for key in keys:
        folded = key.casefold()
        if folded in seen and seen[folded] not in repeated:
            repeated.append(seen[folded])
        _ = seen.setdefault(folded, key)
    return repeated

"""Reading a policy from YAML and hashing it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml
from pydantic import ValidationError

from ._errors import PolicyError
from ._policy import Policy

if TYPE_CHECKING:
    from collections.abc import Hashable


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys instead of keeping the last one."""


def _construct_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
) -> dict[Hashable, object]:
    """Build a mapping, refusing a key that repeats.

    A repeated table in a security policy silently overriding the first one is how a
    reviewer approves a file that means something else.

    Args:
        loader: _UniqueKeyLoader - The running loader.
        node: yaml.MappingNode - The mapping node.

    Returns:
        dict[Hashable, object] - The constructed mapping.

    Raises:
        yaml.constructor.ConstructorError: If a key repeats.

    """
    seen: set[Hashable] = set()
    for key_node, _ in cast("list[tuple[yaml.Node, yaml.Node]]", node.value):
        key = cast("Hashable", loader.construct_object(key_node))  # pyright: ignore[reportUnknownMemberType]
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def parse_policy(text: str, *, source: str = "<policy>") -> Policy:
    """Parse and validate a policy from YAML text.

    Args:
        text: str - YAML text.
        source: str - Where the text came from, used in error messages.

    Returns:
        Policy - The validated policy.

    Raises:
        PolicyError: If the text is not valid YAML or breaks schema v1.

    """
    try:
        data = cast("object", yaml.load(text, Loader=_UniqueKeyLoader))  # ruff: ignore[unsafe-yaml-load]
    except yaml.YAMLError as error:
        msg = f"{source}: invalid YAML: {error}"
        raise PolicyError(msg) from error
    try:
        return Policy.model_validate(data)
    except ValidationError as error:
        problems = "\n".join(
            f"  {'.'.join(map(str, item['loc'])) or '<root>'}: {item['msg']}"
            for item in error.errors()
        )
        msg = f"{source}: invalid policy:\n{problems}"
        raise PolicyError(msg) from error


def load_policy(path: str | Path) -> Policy:
    """Read and validate a policy file.

    Args:
        path: str | Path - Path to the YAML file.

    Returns:
        Policy - The validated policy.

    Raises:
        PolicyError: If the file cannot be read or does not hold a valid policy.

    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        msg = f"{path}: cannot read: {error.strerror}"
        raise PolicyError(msg) from error
    return parse_policy(text, source=str(path))


def policy_hash(policy: Policy) -> str:
    """Hash the policy's meaning, so formatting and comments do not change it.

    Defaults are part of the hash: a new library default changes what the policy does.

    Args:
        policy: Policy - The policy.

    Returns:
        str - `sha256:` followed by the hex digest.

    """
    canonical = json.dumps(
        policy.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"

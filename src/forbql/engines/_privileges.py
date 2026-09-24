"""What a database role may do beyond reading, as found when a session opens."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PrivilegeReport:
    """Findings of the startup privilege check.

    Attributes:
        refusals: tuple[str, ...] - Rights that break a guarantee; forbql will not
            start with them.
        warnings: tuple[str, ...] - Rights worth revoking that break none, each with
            the command that revokes it where there is one.

    """

    refusals: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether forbql may start: nothing was refused."""
        return not self.refusals

"""Annotation markers for use with ``typing.Annotated``.

Example::

    from typing import Annotated
    from python_di import Named, Inject

    class OrderService:
        def __init__(
            self,
            cache: Annotated[Cache, Named("primary")],
            timeout: Annotated[int, Inject(config="order.timeout")],
        ): ...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Named:
    """Select a named binding for a dependency."""

    name: str


@dataclass(frozen=True, slots=True)
class Inject:
    """Inject a configuration value by dotted key path."""

    config: str

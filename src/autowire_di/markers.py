"""Annotation markers for use with ``typing.Annotated``.

Example::

    from typing import Annotated
    from autowire_di import Named, Inject, Assisted

    class OrderService:
        def __init__(
            self,
            cache: Annotated[Cache, Named("primary")],
            timeout: Annotated[int, Inject(config="order.timeout")],
            amount: Annotated[float, Assisted()],
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


@dataclass(frozen=True, slots=True)
class Assisted:
    """Mark a constructor parameter as caller-provided (not injected by the container).

    Used with :meth:`Container.create_factory` to generate factory functions
    that accept assisted parameters while auto-wiring the rest::

        class Payment:
            def __init__(
                self,
                gateway: PaymentGateway,           # injected by container
                amount: Annotated[float, Assisted()],  # provided by caller
                currency: Annotated[str, Assisted()],  # provided by caller
            ): ...

        make_payment = container.create_factory(Payment)
        payment = make_payment(amount=100.0, currency="USD")
    """

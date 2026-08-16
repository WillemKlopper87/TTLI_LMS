"""Card payment providers (03 §5.2/5.7).

`base.py` is the provider-agnostic contract; each concrete gateway
(`payfast.py`, and whatever follows it — see `payfast.py`'s own docstring
for why a Merchant-of-Record integration for international sales is a
likely next addition, not a redesign) implements it. `services/orders.py`
and `routers/webhooks.py` depend only on the protocol, never on a specific
provider's field names.
"""

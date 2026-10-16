"""Sink metadata used to keep externally sourced values from authorizing actions."""

SINK_WORDS = {
    "recipient": "recipient", "email": "recipient", "to": "recipient", "iban": "address",
    "account": "address", "url": "url", "link": "url", "amount": "amount", "price": "amount",
    "body": "body", "message": "body", "text": "body", "file": "identifier", "id": "identifier",
    "channel": "identifier", "user": "identifier", "username": "identifier",
}


def sink_map(params_schema, high_impact: bool = False) -> dict[str, str]:
    output = {}
    for name in getattr(params_schema, "model_fields", {}):
        lowered = name.casefold()
        kind = next((value for token, value in SINK_WORDS.items() if token in lowered), None)
        if kind or high_impact:
            output[name] = kind or "identifier"
    return output

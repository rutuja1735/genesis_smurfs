"""Conservative free-text output trust defaults for AgentDojo tools."""

TRUSTED_FIELDS = {"balance", "iban", "account_id", "user_id", "transaction_id", "date"}
UNTRUSTED_WORDS = {"email", "message", "body", "content", "file", "webpage", "page", "description", "text", "review", "channel"}


def output_trust(tool_name: str, params_schema) -> dict[str, str]:
    names = set(getattr(params_schema, "model_fields", {}))
    # The adapter treats output values as untrusted by default. Core provenance has
    # field-level trust; these keys are retained for downstream adapter consumers.
    return {name: ("trusted" if name.casefold() in TRUSTED_FIELDS else "untrusted") for name in names}

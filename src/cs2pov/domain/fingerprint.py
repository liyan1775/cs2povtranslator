import hashlib, json
from .errors import DomainSchemaError


def canonical_json_bytes(value):
    def check(v):
        if isinstance(v, dict):
            if any(not isinstance(k, str) for k in v):
                raise TypeError("keys")
            for x in v.values():
                check(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                check(x)
        elif v is not None and not isinstance(v, (str, int, float, bool)):
            raise TypeError("value")

    try:
        check(value)
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise DomainSchemaError(
            "domain_field_invalid", "字段无法规范化。", "请修正后重试。"
        ) from exc


def content_fingerprint(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

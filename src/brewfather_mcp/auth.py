import hmac


def is_authorized(authorization: str | None, token: str | None) -> bool:
    """Check an `Authorization` header against the configured bearer token.

    Fails closed: with no token configured, nothing is authorized. Both sides are
    compared as bytes, because `hmac.compare_digest` raises TypeError on a str with
    non-ASCII characters, and a header can contain them.
    """
    if not token:
        return False
    expected = f"Bearer {token}".encode()
    try:
        provided = (authorization or "").encode("utf-8")
    except UnicodeEncodeError:  # lone surrogate: not a valid header
        return False
    return hmac.compare_digest(provided, expected)

from urllib.parse import urlsplit


class PolicyError(ValueError):
    pass


def validate_target(target: str, demo_origin: str) -> str:
    """Deliberately no DNS: milestone 1 permits only the bundled demo origin."""
    if len(target) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in target):
        raise PolicyError("Target must be a short ASCII URL without whitespace")
    if any(c in target for c in ("\\", "%", "?", "#")):
        raise PolicyError("Escapes, queries, fragments and backslashes are not allowed")
    try:
        parsed = urlsplit(target)
        if parsed.username is not None or parsed.password is not None:
            raise PolicyError("URL credentials are not allowed")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin != demo_origin or parsed.hostname != "127.0.0.1" or not target.startswith(demo_origin + "/"):
            raise PolicyError("This milestone only permits http://127.0.0.1:8001")
        # An explicit allowlist also prevents probing unrelated loopback services.
        if parsed.path not in ("/vulnerable", "/hardened", "/redirect"):
            raise PolicyError("Choose /vulnerable, /hardened or /redirect on the demo")
        _ = parsed.port
    except ValueError as exc:
        if isinstance(exc, PolicyError):
            raise
        raise PolicyError("Malformed target URL") from exc
    return target


def validate_action(tool: str, target: str, scope: list[str], demo_origin: str):
    if tool != "http_headers":
        raise PolicyError("Tool is not allowlisted")
    validate_target(target, demo_origin)
    if target not in scope:
        raise PolicyError("Target is outside this assessment's exact URL scope")

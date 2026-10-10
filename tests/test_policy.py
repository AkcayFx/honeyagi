import pytest
from app.policy import PolicyError, validate_target, validate_action
from app.config import Settings

ORIGIN = "http://127.0.0.1:8001"


@pytest.mark.parametrize("target", [
    "https://example.com", "http://169.254.169.254/latest/meta-data", "http://192.168.1.1/",
    "http://localhost:8001/vulnerable", "http://127.0.0.1:8000/health", "http://127.0.0.2:8001/vulnerable",
    "http://[::1]:8001/vulnerable", "http://2130706433:8001/vulnerable", "http://127.0.0.1.:8001/vulnerable",
    "http://127.0.0.1:08001/vulnerable", "http://user:pass@127.0.0.1:8001/vulnerable",
    ORIGIN + "/vulnerable?url=http://example.com", ORIGIN + "/vulnerable#fragment",
    ORIGIN + "/%76ulnerable", ORIGIN + "/vulnerable/../hardened", ORIGIN + "/vulnerable/",
    ORIGIN + "/vulnerable\\anything", ORIGIN + "/unknown", ORIGIN + "/vulnerable\n",
    " " + ORIGIN + "/vulnerable", "HTTP://127.0.0.1:8001/vulnerable", "http://127.0.0.1:bad/vulnerable",
])
def test_reject_target_encodings_and_other_origins(target):
    with pytest.raises(PolicyError):
        validate_target(target, ORIGIN)


@pytest.mark.parametrize("path", ["/vulnerable", "/hardened", "/redirect"])
def test_demo_targets(path):
    assert validate_target(ORIGIN + path, ORIGIN) == ORIGIN + path


def test_scope_is_exact_url():
    with pytest.raises(PolicyError, match="scope"):
        validate_action("http_headers", ORIGIN + "/hardened", [ORIGIN + "/vulnerable"], ORIGIN)


def test_no_shell_adapter():
    with pytest.raises(PolicyError, match="allowlisted"):
        validate_action("shell", ORIGIN + "/vulnerable", [ORIGIN + "/vulnerable"], ORIGIN)


def test_short_token_fails_configuration(tmp_path):
    with pytest.raises(ValueError, match="24"):
        Settings(db_path=tmp_path / "db", token="weak")

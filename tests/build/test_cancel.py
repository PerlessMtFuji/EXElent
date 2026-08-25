from exelent.build.backend import CancelToken


def test_token_starts_uncancelled():
    assert CancelToken().cancelled is False


def test_cancel_sets_flag():
    token = CancelToken()
    token.cancel()
    assert token.cancelled is True


def test_cancel_is_idempotent():
    token = CancelToken()
    token.cancel()
    token.cancel()
    assert token.cancelled is True

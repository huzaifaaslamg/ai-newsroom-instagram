"""Offline tests for Gemini transient-server retry handling."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gemini_writer


class TemporaryServerError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class FakeModels:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise TemporaryServerError(503)
        return "generated"


class FakeClient:
    def __init__(self, models):
        self.models = models


def test_retries_503_and_then_succeeds():
    models = FakeModels(failures=2)
    client = FakeClient(models)
    with patch.object(gemini_writer, "APIError", TemporaryServerError):
        with patch.object(gemini_writer.time, "sleep") as sleep:
            result = gemini_writer._generate_with_retries(
                client, model="test-model", contents="test prompt", config=None
            )
    assert result == "generated"
    assert models.calls == 3
    assert [call.args[0] for call in sleep.call_args_list] == [8, 20]


def test_non_transient_error_is_not_retried():
    models = FakeModels(failures=1)
    client = FakeClient(models)

    class BadRequestError(Exception):
        code = 400

    with patch.object(gemini_writer, "APIError", BadRequestError):
        with patch.object(gemini_writer.time, "sleep") as sleep:
            try:
                gemini_writer._generate_with_retries(
                    client, model="test-model", contents="test prompt", config=None
                )
            except BadRequestError:
                pass
            else:
                raise AssertionError("Expected non-transient error to be raised")
    assert models.calls == 1
    sleep.assert_not_called()


if __name__ == "__main__":
    test_retries_503_and_then_succeeds()
    test_non_transient_error_is_not_retried()
    print("Gemini retry tests passed.")

import contextlib
import hashlib
import hmac
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests
from pydantic import ValidationError

import apply
from models.application_payload import ApplicationPayload
from models.settings import Settings

VALID = {
    "name": "Test Person",
    "email": "test@example.com",
    "resume": "https://example.com/resume.pdf",
    "location": "Ewing, NJ, USA",
    "linkedin": "https://linkedin.com/in/test",
    "codeLink": "https://gist.github.com/test/abc",
    "yearsPython": 8,
    "yearsDjango": 3,
}
ENDPOINT = "https://api.example.com/apply"
ENV = {"HOWGOOD_ENDPOINT": ENDPOINT, "HOWGOOD_HMAC_SECRET": "k"}


def fake_response(status, text="{}"):
    response = mock.Mock()
    response.status_code = status
    response.text = text
    return response


class InTempDir(unittest.TestCase):
    """Run each test in an empty temp directory, so no real .env or config is picked up."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in [n for n in os.environ if n.startswith("HOWGOOD_")]:
            del os.environ[name]


class ApplicationPayloadTests(unittest.TestCase):
    def test_valid_config_builds_payload(self):
        body = json.loads(ApplicationPayload.model_validate(VALID).model_dump_json(exclude_none=True))
        self.assertEqual(body["name"], "Test Person")
        self.assertEqual(body["yearsDjango"], 3)

    def test_missing_required_field_is_reported(self):
        config = {k: v for k, v in VALID.items() if k != "codeLink"}
        with self.assertRaises(ValidationError) as ctx:
            ApplicationPayload.model_validate(config)
        self.assertIn("codeLink", str(ctx.exception))

    def test_blank_required_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            ApplicationPayload.model_validate({**VALID, "email": "  "})

    def test_years_must_be_integers(self):
        with self.assertRaises(ValidationError):
            ApplicationPayload.model_validate({**VALID, "yearsPython": "8"})

    def test_unset_optional_fields_are_left_out(self):
        body = json.loads(ApplicationPayload.model_validate(VALID).model_dump_json(exclude_none=True))
        self.assertNotIn("notes", body)
        self.assertNotIn("repos", body)

    def test_unknown_config_keys_never_reach_the_body(self):
        config = {**VALID, "unexpected": "do-not-send"}
        body = ApplicationPayload.model_validate(config).model_dump_json(exclude_none=True)
        self.assertNotIn("unexpected", body)
        self.assertNotIn("do-not-send", body)

    def test_schema_example_is_a_valid_payload(self):
        for example in ApplicationPayload.model_json_schema()["examples"]:
            ApplicationPayload.model_validate(example)

    def test_non_ascii_characters_are_preserved(self):
        body = ApplicationPayload.model_validate({**VALID, "name": "José"}).model_dump_json()
        self.assertIn("José", body)


class SettingsTests(InTempDir):
    def test_reads_from_environment(self):
        with mock.patch.dict(os.environ, ENV):
            settings = Settings()
        self.assertEqual(str(settings.endpoint), ENDPOINT)
        self.assertEqual(settings.hmac_secret.get_secret_value(), "k")

    def test_reads_from_dotenv_file(self):
        Path(".env").write_text(
            "HOWGOOD_ENDPOINT=https://dotenv.example.com/apply\nHOWGOOD_HMAC_SECRET=from-file\n"
        )
        settings = Settings()
        self.assertEqual(str(settings.endpoint), "https://dotenv.example.com/apply")
        self.assertEqual(settings.hmac_secret.get_secret_value(), "from-file")

    def test_environment_wins_over_dotenv_file(self):
        Path(".env").write_text(
            "HOWGOOD_ENDPOINT=https://dotenv.example.com/apply\nHOWGOOD_HMAC_SECRET=from-file\n"
        )
        with mock.patch.dict(os.environ, {"HOWGOOD_HMAC_SECRET": "from-env"}):
            settings = Settings()
        self.assertEqual(settings.hmac_secret.get_secret_value(), "from-env")

    def test_missing_settings_are_reported(self):
        with self.assertRaises(ValidationError) as ctx:
            Settings()
        self.assertIn("hmac_secret", str(ctx.exception))
        self.assertIn("endpoint", str(ctx.exception))

    def test_secret_is_hidden_in_repr(self):
        with mock.patch.dict(os.environ, {**ENV, "HOWGOOD_HMAC_SECRET": "super-secret"}):
            settings = Settings()
        self.assertNotIn("super-secret", repr(settings))
        self.assertNotIn("super-secret", str(settings))


class SigningTests(unittest.TestCase):
    def test_signature_matches_independent_hmac(self):
        body = '{"a":1}'
        expected = hmac.new(b"k", b'{"a":1}', hashlib.sha256).hexdigest()
        self.assertEqual(apply.sign(body, "k"), expected)

    def test_signature_changes_when_the_body_changes(self):
        self.assertNotEqual(apply.sign('{"a":1}', "k"), apply.sign('{"a":2}', "k"))


class SubmitTests(unittest.TestCase):
    def test_returns_on_success_without_retry(self):
        session = mock.Mock()
        session.post.return_value = fake_response(201)
        response = apply.submit("{}", "sig", ENDPOINT, session=session, backoff=0)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.post.call_args.args[0], ENDPOINT)

    def test_retries_server_errors_then_succeeds(self):
        session = mock.Mock()
        session.post.side_effect = [fake_response(503), fake_response(201)]
        response = apply.submit("{}", "sig", ENDPOINT, session=session, backoff=0)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(session.post.call_count, 2)

    def test_does_not_retry_client_errors(self):
        session = mock.Mock()
        session.post.return_value = fake_response(400, '{"error":"bad"}')
        response = apply.submit("{}", "sig", ENDPOINT, session=session, backoff=0)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(session.post.call_count, 1)

    def test_retries_network_errors_then_gives_up(self):
        session = mock.Mock()
        session.post.side_effect = requests.ConnectionError("down")
        with self.assertRaises(RuntimeError):
            apply.submit("{}", "sig", ENDPOINT, session=session, retries=2, backoff=0)
        self.assertEqual(session.post.call_count, 2)


class MainTests(InTempDir):
    def setUp(self):
        super().setUp()
        Path("config.json").write_text(json.dumps(VALID))
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dry_run_sends_nothing(self):
        with mock.patch("apply.submit") as submit:
            self.assertEqual(apply.main(["--dry-run"]), 0)
        submit.assert_not_called()

    def test_dry_run_never_prints_the_secret(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HOWGOOD_HMAC_SECRET": "super-secret"}):
            with contextlib.redirect_stdout(out):
                apply.main(["--dry-run"])
        self.assertIn(ENDPOINT, out.getvalue())
        self.assertNotIn("super-secret", out.getvalue())

    def test_missing_settings_exit_before_any_request(self):
        del os.environ["HOWGOOD_HMAC_SECRET"]
        with mock.patch("apply.submit") as submit:
            self.assertEqual(apply.main([]), 2)
        submit.assert_not_called()

    def test_invalid_config_exits_before_any_request(self):
        Path("config.json").write_text(json.dumps({**VALID, "email": ""}))
        with mock.patch("apply.submit") as submit:
            self.assertEqual(apply.main([]), 2)
        submit.assert_not_called()

    def test_success_writes_marker_and_blocks_a_second_submit(self):
        with mock.patch("apply.submit", return_value=fake_response(201, '{"ok":true}')) as submit:
            self.assertEqual(apply.main([]), 0)
            self.assertTrue(Path(".submitted").exists())
            self.assertEqual(apply.main([]), 1)
        self.assertEqual(submit.call_count, 1)

    def test_force_resubmits(self):
        with mock.patch("apply.submit", return_value=fake_response(201)) as submit:
            apply.main([])
            apply.main(["--force"])
        self.assertEqual(submit.call_count, 2)

    def test_client_error_does_not_write_marker(self):
        with mock.patch("apply.submit", return_value=fake_response(422, "bad field")):
            self.assertEqual(apply.main([]), 1)
        self.assertFalse(Path(".submitted").exists())

    def test_the_signed_body_is_the_body_sent_to_the_configured_endpoint(self):
        with mock.patch("apply.submit", return_value=fake_response(201)) as submit:
            apply.main([])
        body, signature, endpoint = submit.call_args.args[:3]
        self.assertEqual(signature, apply.sign(body, "k"))
        self.assertEqual(endpoint, ENDPOINT)


if __name__ == "__main__":
    unittest.main()

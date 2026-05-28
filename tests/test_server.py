import html
import os
import unittest

import server


class ServerFormTests(unittest.TestCase):
    def test_parse_form_decodes_urlencoded_values(self) -> None:
        form = server.parse_form(
            b"chatgpt_prompt_id=pmpt_123&telegram_bot_token=123%3Aabc&openai_api_key=sk-test"
        )

        self.assertEqual(form["chatgpt_prompt_id"], "pmpt_123")
        self.assertEqual(form["telegram_bot_token"], "123:abc")
        self.assertEqual(form["openai_api_key"], "sk-test")

    def test_normalize_setup_rejects_missing_required_fields(self) -> None:
        ok, message, config = server.normalize_setup({"chatgpt_prompt_id": "pmpt_123"})

        self.assertFalse(ok)
        self.assertIn("Telegram Bot HTTP API Token", message)
        self.assertIn("OpenAI API Key", message)
        self.assertEqual(config, {})

    def test_normalize_setup_trims_required_fields(self) -> None:
        ok, message, config = server.normalize_setup(
            {
                "chatgpt_prompt_id": " pmpt_123 ",
                "telegram_bot_token": " 123:abc ",
                "openai_api_key": " sk-test ",
            }
        )

        self.assertTrue(ok)
        self.assertEqual(message, "")
        self.assertEqual(config["chatgpt_prompt_id"], "pmpt_123")
        self.assertEqual(config["telegram_bot_token"], "123:abc")
        self.assertEqual(config["openai_api_key"], "sk-test")


class ServerSessionTests(unittest.TestCase):
    def test_recent_messages_keeps_only_last_hour(self) -> None:
        now = 1_700_000_000
        session = {
            "messages": [
                {"ts": now - 3_601, "role": "user", "content": "old"},
                {"ts": now - 3_600, "role": "user", "content": "still recent"},
                {"ts": now - 10, "role": "assistant", "content": "recent answer"},
                {"ts": now - 5, "role": "system", "content": "ignored role"},
                {"ts": now - 5, "role": "user", "content": ""},
                {"ts": "bad", "role": "user", "content": "bad timestamp"},
            ]
        }

        self.assertEqual(
            server.get_recent_messages(session, now),
            [
                {"role": "user", "content": "still recent"},
                {"role": "assistant", "content": "recent answer"},
            ],
        )

    def test_recent_messages_handles_missing_history(self) -> None:
        self.assertEqual(server.get_recent_messages({}, 1_700_000_000), [])


class TelegramFormattingTests(unittest.TestCase):
    def test_format_for_telegram_escapes_html_and_formats_bold(self) -> None:
        formatted = server.format_for_telegram("Hello **world** <script>")

        self.assertIn("Hello <b>world</b>", formatted)
        self.assertIn(html.escape("<script>"), formatted)

    def test_format_for_telegram_renders_markdown_tables_as_preformatted_text(self) -> None:
        formatted = server.format_for_telegram("| Name | Value |\n| --- | --- |\n| A | 1 |")

        self.assertTrue(formatted.startswith("<pre>"))
        self.assertIn("Name", formatted)
        self.assertIn("-+-", formatted)
        self.assertTrue(formatted.endswith("</pre>"))


class ConfigurationTests(unittest.TestCase):
    def test_resolve_data_path_accepts_relative_path_from_environment(self) -> None:
        previous = os.environ.get("DATA_PATH")
        os.environ["DATA_PATH"] = "./custom-data"
        try:
            self.assertEqual(server.resolve_data_path(), (server.BASE_DIR / "custom-data").resolve())
        finally:
            if previous is None:
                os.environ.pop("DATA_PATH", None)
            else:
                os.environ["DATA_PATH"] = previous


if __name__ == "__main__":
    unittest.main()

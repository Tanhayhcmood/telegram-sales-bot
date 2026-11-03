import asyncio
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

language = load_module("language_under_test", "app/services/ai/language.py")
direct_questions = load_module("direct_questions_under_test", "app/services/sales/direct_questions.py")
# Keep this test focused on plan routing, not the free-server integration.
direct_questions._is_free_server_request = lambda _text: False

class PersianPlanFollowupTest(unittest.TestCase):
    def test_greeting_game_smaller_plan_sequence(self):
        detect = lambda text: asyncio.run(language.detect_language(text, fallback_language="en"))
        self.assertEqual(detect("با ما"), "fa")
        self.assertEqual(detect("گفتم که"), "fa")

        history = [
            {"role": "user", "content": "سلام"},
            {"role": "assistant", "content": "سلام! سرور رو برای چی می‌خوای؛ گیم، بات یا سایت؟"},
        ]
        game_language = detect("گیم")
        power_reply = direct_questions.get_direct_sales_reply("گیم", history, game_language)
        self.assertIn("POWER", power_reply)
        history.extend([
            {"role": "user", "content": "گیم"},
            {"role": "assistant", "content": power_reply},
        ])
        self.assertEqual(direct_questions._current_plan(history), "POWER")

        text = "پلن کوچیکتری دارید؟"
        language_code = detect(text)
        self.assertEqual(language_code, "fa")
        reply = direct_questions.get_direct_sales_reply(text, history, language_code)
        self.assertIn("ENTRY LEVEL", reply)
        self.assertNotIn("سرور رو برای چی می‌خوای", reply)

if __name__ == "__main__":
    unittest.main()

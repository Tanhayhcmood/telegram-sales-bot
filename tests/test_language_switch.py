import unittest

from app.services.ai.language import detect_language


class LanguageSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_latest_message_can_choose_a_different_language(self):
        self.assertEqual(await detect_language("Hi"), "en")
        self.assertEqual(await detect_language("سلام"), "fa")
        self.assertEqual(await detect_language("VPS"), "en")
        self.assertEqual(await detect_language("Ubuntu 22.04 LTS"), "en")

    async def test_latest_message_keeps_its_detected_language(self):
        self.assertEqual(await detect_language("Hallo, ich brauche einen Server"), "de")
        self.assertEqual(await detect_language("مرحبا أريد خادما"), "ar")
        self.assertEqual(await detect_language("Mujhe lena hai"), "hi")
        self.assertEqual(await detect_language("bonjour je veux un serveur"), "fr")

    async def test_persian_text_uses_only_persian_mode(self):
        self.assertEqual(await detect_language("برای گیم سرور میخوام"), "fa")


if __name__ == "__main__":
    unittest.main()
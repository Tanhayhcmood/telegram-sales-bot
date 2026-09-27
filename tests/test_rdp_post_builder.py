import unittest

from app.services.content.rdp_post_builder import build_rdp_post


class RdpPostBuilderTests(unittest.TestCase):
    def test_headline_uses_strong_rdp_and_vps_keywords(self):
        post, _ = build_rdp_post(
            ip="203.0.113.10",
            port=3389,
            username="ignored",
            password="secret",
            country_name="United States",
            country_flag="🇺🇸",
            seed=1,
        )

        self.assertTrue(
            post.startswith("🔥 FREE RDP • FREE VPS • WINDOWS RDP • CLOUD VPS 🔥\n")
        )
        self.assertNotIn("THUNDER DROP", post)

    def test_post_text_promises_a_six_hour_refresh(self):
        post, _ = build_rdp_post(
            ip="203.0.113.10",
            port=3389,
            username="ignored",
            password="secret",
            country_name="United States",
            country_flag="🇺🇸",
            seed=2,
        )

        self.assertIn("every ~6 hours", post)
        self.assertNotIn("~3 hours", post)


if __name__ == "__main__":
    unittest.main()
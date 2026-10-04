import unittest

from app.services.content.rdp_post_builder import (
    build_rdp_post,
    build_rdp_test_caption,
    fit_rdp_caption,
    rdp_caption_utf16_length,
)


class RdpPostBuilderTests(unittest.TestCase):
    def build(self, **overrides):
        values = {
            "ip": "203.0.113.10",
            "port": 3389,
            "username": "ignored",
            "password": "test-secret",
            "country_name": "Unknown",
            "country_flag": "",
            "seed": 123,
            "channel_username": "freeserver11",
        }
        values.update(overrides)
        return build_rdp_post(**values)

    def test_approved_copy_excludes_site_promotions(self):
        post, image = self.build()
        self.assertTrue(post.startswith("🔥 FREE RDP • FREE VPS • WINDOWS RDP • CLOUD VPS 🔥\n"))
        self.assertEqual(image, "GENERATE_VPS_DESKTOP")
        self.assertNotIn("Buy directly from the site", post)
        self.assertNotIn("VPS24H.COM", post)
        self.assertIn("📍 🌐 Unknown · Port 3389", post)
        self.assertIn("every ~6 hours", post)
        self.assertIn("<b>⚡ Instant purchase 24/7 from Telegram admin <a href=\"https://t.me/VPS24H\">@VPS24H</a></b>", post)
        admin_cta = '<b>⚡ Instant purchase 24/7 from Telegram admin <a href="https://t.me/VPS24H">@VPS24H</a></b>'
        self.assertEqual(post.count(admin_cta), 2)

    def test_only_server_fields_change_and_channel_link_is_scoped(self):
        post, _ = self.build(ip="198.51.100.24", password="p<&ss", country_name="Germany", country_flag="🇩🇪")
        self.assertIn("198.51.100.24:3389", post)
        self.assertIn("p&lt;&amp;ss", post)
        self.assertIn("🇩🇪 Germany", post)
        self.assertIn('<a href="https://t.me/freeserver11">channel</a>', post)
        self.assertIn("👤  Administrator", post)

    def test_sample_fits_one_photo_caption_without_trimming(self):
        post, _ = self.build(password="TEST-ONLY-NOT-VALID")
        caption, removed = fit_rdp_caption(post)

        self.assertEqual(caption, post)
        self.assertEqual(removed, 0)
        self.assertLessEqual(rdp_caption_utf16_length(caption), 1024)
        self.assertIn("🚀 Connect: mstsc → paste IP → login", caption)
        self.assertTrue(caption.endswith("</b>"))

    def test_long_fake_details_compact_only_divider_rules(self):
        post, _ = self.build(
            ip="255.255.255.255",
            password="FAKE-TEST-ONLY-PASSWORD-1234" + "X" * 106,
            country_name="United Arab Emirates",
            country_flag="🇦🇪",
        )
        caption, removed = fit_rdp_caption(post)

        def without_rules(value):
            return [
                line for line in value.split("\n")
                if not (line and line[0] in "═─" and all(char == line[0] for char in line))
            ]

        self.assertGreater(removed, 0)
        self.assertLessEqual(rdp_caption_utf16_length(caption), 1024)
        self.assertEqual(without_rules(caption), without_rules(post))
        self.assertIn("FAKE-TEST-ONLY-PASSWORD-1234", caption)

    def test_unfit_caption_fails_instead_of_becoming_a_second_message(self):
        with self.assertRaisesRegex(ValueError, "single-photo caption limit"):
            fit_rdp_caption("x" * 1025)

    def test_one_channel_sample_is_clearly_fake_and_fits_in_one_caption(self):
        caption = build_rdp_test_caption("@freeserver11")
        fitted, _ = fit_rdp_caption(caption)

        self.assertLessEqual(rdp_caption_utf16_length(fitted), 1024)
        self.assertTrue(fitted.startswith("🧪 TEST ONLY — NOT A REAL SERVER\n\n"))
        self.assertIn("203.0.113.42", fitted)
        self.assertIn("TEST-ONLY-NOT-A-REAL-LOGIN", fitted)
        self.assertIn('<a href="https://t.me/freeserver11">channel</a>', fitted)
        self.assertNotIn("Buy directly from the site", fitted)
        self.assertNotIn("VPS24H.COM", fitted)


if __name__ == "__main__":
    unittest.main()

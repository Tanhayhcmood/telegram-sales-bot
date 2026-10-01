import unittest

from app.services.content.rdp_post_builder import build_rdp_post


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

    def test_approved_copy_and_clickable_site_label(self):
        post, image = self.build()
        self.assertTrue(post.startswith("🔥 FREE RDP • FREE VPS • WINDOWS RDP • CLOUD VPS 🔥\n"))
        self.assertEqual(image, "GENERATE_VPS_DESKTOP")
        site = '<b>🌐 Buy directly from the site : <a href="https://vps24h-website.onrender.com/">VPS24H.COM</a></b>'
        self.assertEqual(post.count(site), 2)
        self.assertIn("VPS24H.COM", post)
        self.assertIn("📍 🌐 Unknown · Port 3389", post)
        self.assertIn("every ~6 hours", post)
        self.assertIn("<b>⚡ Instant purchase 24/7 from Telegram admin <a href=\"https://t.me/VPS24H\">@VPS24H</a></b>", post)

    def test_only_server_fields_change_and_channel_link_is_scoped(self):
        post, _ = self.build(ip="198.51.100.24", password="p<&ss", country_name="Germany", country_flag="🇩🇪")
        self.assertIn("198.51.100.24:3389", post)
        self.assertIn("p&lt;&amp;ss", post)
        self.assertIn("🇩🇪 Germany", post)
        self.assertIn('<a href="https://t.me/freeserver11">channel</a>', post)
        self.assertIn("👤  Administrator", post)


if __name__ == "__main__":
    unittest.main()

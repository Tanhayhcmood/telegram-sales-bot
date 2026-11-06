import unittest
from html.parser import HTMLParser

from app.services.content.rdp_post_builder import (
    build_rdp_post,
    build_rdp_test_caption,
    build_vps_promo_post,
    fit_rdp_caption,
    rdp_caption_utf16_length,
)


class TelegramHtmlValidator(HTMLParser):
    ALLOWED_TAGS = {"b", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED_TAGS or attrs:
            self.errors.append(f"disallowed tag or attributes: {tag} {attrs}")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(f"unbalanced tag: {tag}")


class VpsPromoTemplateTests(unittest.TestCase):
    def render(self, **overrides):
        values = {
            "language": "en",
            "location": "Ask support for current regions",
            "cpu": "4 vCPU",
            "ram": "8 GB",
            "os_name": "Ubuntu 24.04",
            "time_value": "06 Nov 2026 12:30",
            "admin_username": "VPS24H",
            "seed": 0,
        }
        values.update(overrides)
        return build_vps_promo_post(**values)[0]

    def test_template_html_is_valid_and_caption_fits_telegram(self):
        caption = self.render()
        parser = TelegramHtmlValidator()
        parser.feed(caption)
        parser.close()

        self.assertEqual(parser.errors, [])
        self.assertEqual(parser.stack, [])
        self.assertLessEqual(rdp_caption_utf16_length(caption), 1024)
        self.assertEqual(fit_rdp_caption(caption), (caption, 0))

    def test_dynamic_values_are_escaped(self):
        caption = self.render(
            location='Region <West & "Central">',
            time_value='06 <script> & "now"',
            admin_username='<team&service>',
        )

        self.assertIn("Region &lt;West &amp; &quot;Central&quot;&gt;", caption)
        self.assertIn("06 &lt;script&gt; &amp; &quot;now&quot;", caption)
        self.assertIn("@&lt;team&amp;service&gt;", caption)

    def test_configured_specs_are_rendered_and_escaped(self):
        caption = self.render(
            cpu="<8 vCPU>",
            ram='16 GB & "fast"',
            os_name="Ubuntu <24.04>",
        )
        self.assertIn("&lt;8 vCPU&gt;", caption)
        self.assertIn("16 GB &amp; &quot;fast&quot;", caption)
        self.assertIn("Ubuntu &lt;24.04&gt;", caption)
        self.assertNotIn("{admin_username}", caption)

    def test_missing_and_very_long_specs_keep_caption_compact(self):
        caption = self.render(cpu="", ram="", os_name="")
        self.assertIn("Ask for specs", caption)
        long_caption = self.render(
            location="&" * 5000,
            cpu="&" * 5000,
            ram="&" * 5000,
            os_name="&" * 5000,
        )
        self.assertLessEqual(rdp_caption_utf16_length(long_caption), 1024)
        self.assertEqual(fit_rdp_caption(long_caption), (long_caption, 0))

    def test_public_template_never_includes_scan_credentials_or_login_steps(self):
        caption, _ = build_rdp_post(
            ip="198.51.100.24",
            port=3389,
            username="private-user",
            password="private-password",
            country_name="Test Region",
            country_flag="🏳️",
            seed=1,
        )

        for sensitive_value in ("198.51.100.24", "3389", "private-user", "private-password", "mstsc"):
            self.assertNotIn(sensitive_value, caption)
        self.assertIn("@VPS24H", caption)

    def test_all_supported_languages_render_and_unknown_uses_english(self):
        for language in ("en", "fa", "ar", "tr", "ru", "de", "fr", "es", "fa-IR"):
            with self.subTest(language=language):
                caption = self.render(language=language)
                self.assertTrue(caption)
                self.assertLessEqual(rdp_caption_utf16_length(caption), 1024)

        self.assertEqual(self.render(language="xx"), self.render(language="en"))

    def test_three_header_and_sales_variants_rotate_deterministically(self):
        captions = [self.render(seed=seed) for seed in range(3)]
        self.assertEqual(len(set(captions)), 3)

    def test_legacy_test_caption_contains_no_fake_access_details(self):
        caption = build_rdp_test_caption("@sample_channel")
        self.assertTrue(caption.startswith("🧪 TEST ONLY — NOT A LIVE SERVER"))
        self.assertNotIn("203.0.113.42", caption)
        self.assertNotIn("TEST-ONLY-NOT-A-REAL-LOGIN", caption)
        self.assertLessEqual(rdp_caption_utf16_length(caption), 1024)

    def test_caption_over_limit_fails_instead_of_sending_a_second_message(self):
        with self.assertRaisesRegex(ValueError, "single-photo caption limit"):
            fit_rdp_caption("x" * 1025)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path


class ChallengeScheduleConfigTests(unittest.TestCase):
    def test_challenges_are_scheduled_every_ten_hours_by_default(self):
        config_source = (
            Path(__file__).resolve().parents[1] / "app" / "core" / "config.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CHALLENGE_INTERVAL_HOURS: int = 10", config_source)


if __name__ == "__main__":
    unittest.main()
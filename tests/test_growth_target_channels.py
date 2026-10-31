import unittest

from app.services.growth.publishing import _merge_target_channels


class GrowthTargetChannelsTests(unittest.TestCase):
    def test_all_21_configured_channels_are_preserved(self):
        registered = [f"-100{index}" for index in range(1, 16)]
        required = [f"-100{index}" for index in range(12, 16)]
        required += [f"@channel{index}" for index in range(1, 7)]

        channels = _merge_target_channels(registered, ",".join(required))

        self.assertEqual(21, len(channels))
        self.assertEqual(len(channels), len(set(channels)))

    def test_values_are_trimmed_and_duplicate_targets_keep_first_order(self):
        channels = _merge_target_channels([" -1001 ", ""], " @alpha, -1001, , @beta ")

        self.assertEqual(["-1001", "@alpha", "@beta"], channels)


if __name__ == "__main__":
    unittest.main()

import unittest

from scripts.train_ryu_kim_stage4_diagnostics import (
    assert_stage4_input_names,
    binary_metrics,
    dose_features,
)


class Stage4DiagnosticsTests(unittest.TestCase):
    def test_stage4_static_features_allowed_but_ids_forbidden(self):
        assert_stage4_input_names(["age", "mssq", "gender_f", "motion_energy"])
        for forbidden in ("fms", "raw_pa_id", "session_uid", "condition", "future_5s_delta_fms"):
            with self.assertRaises(AssertionError):
                assert_stage4_input_names(["age", forbidden])

    def test_binary_metrics(self):
        metrics = binary_metrics([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.2])
        self.assertAlmostEqual(metrics["recall"], 1.0)
        self.assertAlmostEqual(metrics["f1"], 1.0)
        self.assertGreater(metrics["auprc"], 0.9)

    def test_dose_features_are_finite(self):
        window = {
            "x_dynamic": [[1, 0, 0, 0, 1, 0], [2, 0, 0, 0, 2, 0]],
            "missing_mask": [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]],
        }
        values = dose_features(window, dt=0.5)
        self.assertEqual(len(values), 11)
        self.assertTrue(all(value == value for value in values))


if __name__ == "__main__":
    unittest.main()

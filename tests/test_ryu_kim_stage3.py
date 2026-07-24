import unittest

from openrdw_ai.ryu_kim_fms.sequence_models import assert_sequence_input_names, require_torch
from scripts.train_ryu_kim_stage3_experiments import missing_block_class, tensorize_with_strategy


class Stage3ExperimentTests(unittest.TestCase):
    def test_missing_block_class(self):
        self.assertEqual(missing_block_class({"missing_mask": [[0, 0], [0, 0]]}), "no_missing")
        self.assertEqual(missing_block_class({"missing_mask": [[0, 0], [1, 0], [0, 0]]}), "short_contiguous_missing")
        self.assertEqual(missing_block_class({"missing_mask": [[1, 0], [1, 0], [1, 0]]}), "long_contiguous_missing")

    def test_forbidden_stage3_inputs_fail(self):
        valid = [f"feature_{i}" for i in range(18)]
        assert_sequence_input_names(valid)
        for forbidden in ("fms", "age", "gender", "mssq", "raw_pa_id", "session_id", "condition", "future_frames"):
            with self.assertRaises(AssertionError):
                assert_sequence_input_names(["acceleration_x", forbidden])

    def test_forward_fill_is_causal_with_mask_and_time(self):
        try:
            torch, _, _ = require_torch()
        except RuntimeError:
            self.skipTest("PyTorch is not installed")

        class Standardizer:
            mean_ = [0.0, 0.0]
            scale_ = [1.0, 1.0]

        window = {
            "x_dynamic": [[1.0, 2.0], [None, 4.0], [9.0, None]],
            "missing_mask": [[0, 0], [1, 0], [0, 1]],
            "y_fms": 1.0,
        }
        original = tuple(__import__("openrdw_ai.ryu_kim_fms.schema", fromlist=["DYNAMIC_FEATURES"]).DYNAMIC_FEATURES)
        try:
            import scripts.train_ryu_kim_stage3_experiments as stage3

            stage3.DYNAMIC_FEATURES = ("a", "b")
            x, _ = tensorize_with_strategy(torch, [window], Standardizer(), torch.device("cpu"), "ffill_mask_time")
            self.assertEqual(tuple(x.shape), (1, 3, 6))
            self.assertEqual(float(x[0, 1, 0]), 1.0)
            self.assertEqual(float(x[0, 2, 1]), 4.0)
            self.assertEqual(float(x[0, 2, 5]), 1.0)
        finally:
            stage3.DYNAMIC_FEATURES = original


if __name__ == "__main__":
    unittest.main()

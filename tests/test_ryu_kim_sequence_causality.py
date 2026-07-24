import unittest

from openrdw_ai.ryu_kim_fms.sequence_models import (
    assert_sequence_input_names,
    build_causal_tcn_model,
    build_lstm_model,
    require_torch,
)


class SequenceCausalityTests(unittest.TestCase):
    def test_forbidden_sequence_inputs_fail(self):
        assert_sequence_input_names([f"feature_{i}" for i in range(12)])
        for forbidden in ("fms", "age", "mssq", "raw_pa_id", "session_id", "condition", "future_frames"):
            with self.assertRaises(AssertionError):
                assert_sequence_input_names(["acceleration_x", forbidden])

    def test_lstm_is_unidirectional(self):
        try:
            _, _, _ = require_torch()
        except RuntimeError:
            self.skipTest("PyTorch is not installed")
        model = build_lstm_model()
        self.assertFalse(model.lstm.bidirectional)

    def test_tcn_future_perturbation_does_not_change_past_outputs(self):
        try:
            torch, _, _ = require_torch()
        except RuntimeError:
            self.skipTest("PyTorch is not installed")
        torch.manual_seed(0)
        model = build_causal_tcn_model(input_channels=12, channels=8, levels=2, kernel_size=3, dropout=0.0)
        model.eval()
        x = torch.randn(2, 20, 12)
        y = model.forward_sequence(x)
        x_changed = x.clone()
        x_changed[:, 15:, :] += 1000.0
        y_changed = model.forward_sequence(x_changed)
        self.assertTrue(torch.allclose(y[:, :15], y_changed[:, :15], atol=1e-5))

    def test_single_batch_gradient(self):
        try:
            torch, _, _ = require_torch()
        except RuntimeError:
            self.skipTest("PyTorch is not installed")
        model = build_lstm_model()
        x = torch.randn(4, 20, 12)
        y = torch.randn(4)
        loss = ((model(x) - y) ** 2).mean()
        loss.backward()
        grad_sum = sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None)
        self.assertGreater(grad_sum, 0.0)


if __name__ == "__main__":
    unittest.main()

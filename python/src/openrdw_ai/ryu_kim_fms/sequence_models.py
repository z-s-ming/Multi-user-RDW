from typing import Dict


FORBIDDEN_SEQUENCE_INPUTS = {
    "fms",
    "fms_history",
    "age",
    "gender",
    "mssq",
    "participant_id",
    "raw_pa_id",
    "session_id",
    "condition",
    "condition_id",
    "filename",
    "source_file",
    "future_frames",
}


def assert_sequence_input_names(feature_names):
    forbidden = FORBIDDEN_SEQUENCE_INPUTS.intersection(set(feature_names))
    if forbidden:
        raise AssertionError(f"Forbidden sequence input features present: {sorted(forbidden)}")


def require_torch():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except Exception as exc:
        raise RuntimeError("PyTorch is required for LSTM/causal TCN sequence models") from exc
    return torch, nn, F


def build_lstm_model(input_size=12, hidden_size=32, num_layers=1, dropout=0.0):
    torch, nn, _ = require_torch()

    class LSTMRegressor(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
                dropout=dropout if num_layers > 1 else 0.0,
                bidirectional=False,
            )
            self.head = nn.Linear(hidden_size, 1)

        def forward(self, x):
            output, _ = self.lstm(x)
            return self.head(output[:, -1, :]).squeeze(-1)

    return LSTMRegressor()


def build_causal_tcn_model(input_channels=12, channels=32, levels=3, kernel_size=3, dropout=0.05):
    torch, nn, F = require_torch()

    class CausalConv1d(nn.Module):
        def __init__(self, in_channels, out_channels, kernel_size, dilation):
            super().__init__()
            self.left_padding = (kernel_size - 1) * dilation
            self.conv = nn.Conv1d(in_channels, out_channels, kernel_size, dilation=dilation)

        def forward(self, x):
            return self.conv(F.pad(x, (self.left_padding, 0)))

    class CausalBlock(nn.Module):
        def __init__(self, in_channels, out_channels, dilation):
            super().__init__()
            self.net = nn.Sequential(
                CausalConv1d(in_channels, out_channels, kernel_size, dilation),
                nn.ReLU(),
                nn.Dropout(dropout),
                CausalConv1d(out_channels, out_channels, kernel_size, dilation),
                nn.ReLU(),
                nn.Dropout(dropout),
            )
            self.residual = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else nn.Identity()

        def forward(self, x):
            return self.net(x) + self.residual(x)

    class CausalTCNRegressor(nn.Module):
        def __init__(self):
            super().__init__()
            blocks = []
            in_ch = input_channels
            for level in range(levels):
                dilation = 2 ** level
                blocks.append(CausalBlock(in_ch, channels, dilation))
                in_ch = channels
            self.tcn = nn.Sequential(*blocks)
            self.head = nn.Linear(channels, 1)

        def forward_sequence(self, x):
            # x: [batch, time, channels] -> [batch, channels, time]
            y = self.tcn(x.transpose(1, 2))
            return self.head(y.transpose(1, 2)).squeeze(-1)

        def forward(self, x):
            return self.forward_sequence(x)[:, -1]

    return CausalTCNRegressor()


def count_trainable_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


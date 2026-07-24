import unittest
import tempfile
from pathlib import Path

from openrdw_ai.ryu_kim_fms.identity import (
    assert_duplicate_groups_not_cross_split,
    assert_entire_column_missing_not_linear_interpolated,
    assert_unique_session_uids,
    assert_unresolved_identities_not_confirmed,
    sha256_file,
    stable_session_uid,
)
from openrdw_ai.ryu_kim_fms.preprocess import Preprocessor, assert_scaler_fit_only_on_train
from openrdw_ai.ryu_kim_fms.split import participant_disjoint_split, validate_participant_disjoint
from openrdw_ai.ryu_kim_fms.window import assert_no_future_frames, generate_causal_windows


def synthetic_rows():
    rows = []
    for participant in ("PA1", "PA2", "PA3", "PA4"):
        for i in range(130):
            rows.append(
                {
                    "participant_id": participant,
                    "session_id": f"{participant}_S1",
                    "condition_id": "Base",
                    "row_index": i,
                    "timestamp": i * 0.5,
                    "fms": float(i % 5),
                    "acceleration_x": 1.0 + i,
                    "acceleration_y": 2.0 + i,
                    "acceleration_z": 3.0 + i,
                    "angular_velocity_x": 0.1 + i,
                    "angular_velocity_y": 0.2 + i,
                    "angular_velocity_z": 0.3 + i,
                    "gender": "f" if participant in ("PA1", "PA3") else "m",
                    "mssq": 10.0,
                    "age": 20.0,
                }
            )
    return rows


class RyuKimPipelineTests(unittest.TestCase):
    def test_participant_disjoint_split(self):
        splits = participant_disjoint_split(["PA1", "PA2", "PA3", "PA4"], 0.5, 0.25, 0.25, 42)
        validate_participant_disjoint(splits)
        self.assertEqual(splits, participant_disjoint_split(["PA1", "PA2", "PA3", "PA4"], 0.5, 0.25, 0.25, 42))
        with self.assertRaises(AssertionError):
            validate_participant_disjoint({"train": ["PA1"], "test": ["PA1"]})

    def test_causal_windows_exclude_fms_and_future_frames(self):
        windows = list(generate_causal_windows(synthetic_rows(), 10.0, 0.5))
        self.assertTrue(windows)
        first = windows[0]
        self.assertEqual(len(first["x_dynamic"]), 20)
        self.assertEqual(len(first["x_dynamic"][0]), 6)
        self.assertNotIn("fms", first["x_dynamic_feature_names"])
        assert_no_future_frames(first)

    def test_standardizer_fits_only_on_training_participants(self):
        rows = synthetic_rows()
        windows = list(generate_causal_windows(rows, 10.0, 0.5))
        train_participants = ["PA1", "PA2"]
        preprocessor = Preprocessor().fit(windows, train_participants)
        assert_scaler_fit_only_on_train(preprocessor, train_participants)
        sample = preprocessor.transform_window(windows[0])
        self.assertEqual(len(sample["x_dynamic"][0]), 6)
        self.assertEqual(len(sample["x_static"]), 5)
        self.assertIn("y_fms", sample)

    def test_session_uid_unique_and_file_hash_reproducible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.csv"
            path.write_text("1,2,3\n", encoding="utf-8")
            first_hash = sha256_file(path)
            second_hash = sha256_file(path)
        self.assertEqual(first_hash, second_hash)
        manifest = [
            {"session_uid": stable_session_uid("a" * 64, "a.csv")},
            {"session_uid": stable_session_uid("b" * 64, "b.csv")},
        ]
        assert_unique_session_uids(manifest)
        with self.assertRaises(AssertionError):
            assert_unique_session_uids([manifest[0], manifest[0]])

    def test_confirmed_duplicate_sessions_cannot_cross_split(self):
        duplicate_report = [
            {
                "confirmed_duplicate": "true",
                "session_uids": "session_a|session_b",
            }
        ]
        assert_duplicate_groups_not_cross_split(duplicate_report, {"session_a": "train", "session_b": "train"})
        with self.assertRaises(AssertionError):
            assert_duplicate_groups_not_cross_split(duplicate_report, {"session_a": "train", "session_b": "test"})

    def test_unresolved_identity_not_silently_confirmed(self):
        assert_unresolved_identities_not_confirmed(
            [{"identity_status": "unresolved", "identity_confidence": "not_confirmed"}]
        )
        with self.assertRaises(AssertionError):
            assert_unresolved_identities_not_confirmed(
                [{"identity_status": "unresolved", "identity_confidence": "confirmed"}]
            )

    def test_entire_column_missing_not_linear_interpolated(self):
        assert_entire_column_missing_not_linear_interpolated(
            [{"missing_pattern": "entire-column missing", "interpolation_allowed": "false"}]
        )
        with self.assertRaises(AssertionError):
            assert_entire_column_missing_not_linear_interpolated(
                [{"missing_pattern": "entire-column missing", "interpolation_allowed": "linear"}]
            )


if __name__ == "__main__":
    unittest.main()

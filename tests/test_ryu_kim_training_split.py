import unittest

from openrdw_ai.ryu_kim_fms.dynamic_baseline import (
    DynamicStandardizer,
    assert_allowed_model_inputs,
    assert_no_future_frames_in_window,
    assert_raw_pa_and_session_disjoint,
    assert_window_does_not_cross_session,
    make_group_kfold_assignments,
    split_windows_by_fold,
)


def synthetic_windows():
    rows = []
    for group in ("PA1", "PA2", "PA3", "PA4", "PA5"):
        for session in range(2):
            for index in range(3):
                rows.append(
                    {
                        "raw_pa_id": group,
                        "session_uid": f"{group}_S{session}",
                        "timestamps": [0.0, 0.5],
                        "start_time": 0.0,
                        "end_time": 0.5,
                        "source_row_end": index,
                        "x_dynamic": [[1.0, 2.0, 3.0, 0.1, 0.2, 0.3], [1.1, 2.1, 3.1, 0.2, None, 0.4]],
                        "missing_mask": [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0]],
                        "x_dynamic_feature_names": [
                            "acceleration_x",
                            "acceleration_y",
                            "acceleration_z",
                            "angular_velocity_x",
                            "angular_velocity_y",
                            "angular_velocity_z",
                        ],
                        "has_missing_dynamic": True,
                        "y_fms": float(index),
                    }
                )
    return rows


class DynamicTrainingSplitTests(unittest.TestCase):
    def test_fixed_seed_group_split_reproducible_and_disjoint(self):
        windows = synthetic_windows()
        weights = {group: 6 for group in ("PA1", "PA2", "PA3", "PA4", "PA5")}
        first = make_group_kfold_assignments(weights, 5, 42)
        second = make_group_kfold_assignments(weights, 5, 42)
        self.assertEqual(first, second)
        train, test = split_windows_by_fold(windows, first, 0)
        assert_raw_pa_and_session_disjoint(train, test)

    def test_forbidden_inputs_fail(self):
        assert_allowed_model_inputs(["acceleration_x", "angular_velocity_z"])
        with self.assertRaises(AssertionError):
            assert_allowed_model_inputs(["acceleration_x", "fms"])
        with self.assertRaises(AssertionError):
            assert_allowed_model_inputs(["age"])
        with self.assertRaises(AssertionError):
            assert_allowed_model_inputs(["session_id"])

    def test_future_frame_and_cross_session_fail(self):
        window = synthetic_windows()[0]
        assert_no_future_frames_in_window(window)
        assert_window_does_not_cross_session(window)
        bad_future = dict(window)
        bad_future["timestamps"] = [0.0, 1.0]
        bad_future["end_time"] = 0.5
        with self.assertRaises(AssertionError):
            assert_no_future_frames_in_window(bad_future)
        bad_session = dict(window)
        bad_session["session_uids"] = ["a", "b"]
        with self.assertRaises(AssertionError):
            assert_window_does_not_cross_session(bad_session)

    def test_standardizer_fit_only_train_and_missing_filled_after_transform(self):
        windows = synthetic_windows()
        scaler = DynamicStandardizer().fit(windows, ["PA1", "PA2"])
        self.assertEqual(scaler.fit_group_ids_, ["PA1", "PA2"])
        transformed = scaler.transform_window(windows[0])
        self.assertEqual(transformed[1][4], 0.0)


if __name__ == "__main__":
    unittest.main()


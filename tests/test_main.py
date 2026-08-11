from gesture_control import main
from gesture_control.main import parse_args, preflight


def test_defaults_are_live_mode():
    args = parse_args([])
    assert args.dry_run is False
    assert args.record is None


def test_dry_run_flag():
    assert parse_args(["--dry-run"]).dry_run is True


def test_record_takes_a_path():
    args = parse_args(["--record", "recordings/x.jsonl"])
    assert args.record == "recordings/x.jsonl"


def test_camera_index_is_an_int():
    assert parse_args(["--camera", "2"]).camera == 2


def test_model_path_override():
    assert parse_args(["--model", "m.task"]).model == "m.task"


def test_preflight_flags_missing_accessibility(tmp_path, monkeypatch):
    model = tmp_path / "model.task"
    model.write_bytes(b"")
    monkeypatch.setattr(main, "accessibility_granted", lambda: False)
    monkeypatch.setattr(main, "request_accessibility", lambda: False)

    problems = preflight(False, str(model))

    assert len(problems) == 1
    assert "accessibility" in problems[0].lower()
    assert "restart" in problems[0].lower()


def test_preflight_passes_when_model_and_accessibility_are_present(tmp_path, monkeypatch):
    model = tmp_path / "model.task"
    model.write_bytes(b"")
    monkeypatch.setattr(main, "accessibility_granted", lambda: True)
    monkeypatch.setattr(main, "request_accessibility", lambda: True)

    assert preflight(False, str(model)) == []


def test_preflight_accepts_access_granted_by_the_request(monkeypatch, tmp_path):
    """The active request is what makes the app appear in the Accessibility list.

    Without it the toggle does not exist for the user to switch on, so a
    preflight that only reads the current state and never asks is a real
    regression. This is the only case where asking changes the outcome.
    """
    model = tmp_path / "hand_landmarker.task"
    model.write_bytes(b"")
    monkeypatch.setattr(main, "accessibility_granted", lambda: False)
    monkeypatch.setattr(main, "request_accessibility", lambda: True)
    assert main.preflight(dry_run=False, model=str(model)) == []

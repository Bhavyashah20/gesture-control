import sys

from gesture_control import main
from gesture_control.main import parse_args, preflight


def _fake_camera_class(*, open_ok=True, read_ok=True):
    """Stand-in for Camera so preflight tests never touch real hardware.

    Mirrors the module-level monkeypatch pattern already used for
    accessibility_granted/request_accessibility: preflight looks up
    `main.Camera` at call time, so tests rebind that name instead of hitting
    cv2/AVFoundation.
    """

    class _FakeCamera:
        def __init__(self, index=0, **_kwargs):
            self.index = index
            self.closed = False

        def open(self):
            if not open_ok:
                raise RuntimeError(
                    f"Cannot open camera {self.index}. Grant camera access to your "
                    "terminal in System Settings, Privacy and Security, Camera."
                )

        def read(self):
            return (read_ok, object() if read_ok else None)

        def close(self):
            self.closed = True

    return _FakeCamera


def test_main_honours_dry_run_from_argv(monkeypatch):
    """The documented safe command must actually select the dry-run actuator.

    main() previously passed [] to argparse when argv was None, so every CLI
    flag was discarded and --dry-run posted real events. A fake preflight that
    unconditionally returns a problem is not enough to catch this: it must
    also record what dry_run value it was actually called with, otherwise
    the assertion passes whether or not the bug is present.
    """
    monkeypatch.setattr(sys, "argv", ["gesture-control", "--dry-run"])
    captured = {}

    def fake_preflight(dry_run, model=None, camera_index=None):
        captured["dry_run"] = dry_run
        return ["stop here"]  # short-circuit before any hardware is touched

    monkeypatch.setattr(main, "preflight", fake_preflight)
    rc = main.main()
    assert rc == 1
    assert captured["dry_run"] is True


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
    monkeypatch.setattr(main, "Camera", _fake_camera_class())

    problems = preflight(False, str(model))

    assert len(problems) == 1
    assert "accessibility" in problems[0].lower()
    assert "restart" in problems[0].lower()


def test_preflight_passes_when_model_and_accessibility_are_present(tmp_path, monkeypatch):
    model = tmp_path / "model.task"
    model.write_bytes(b"")
    monkeypatch.setattr(main, "accessibility_granted", lambda: True)
    monkeypatch.setattr(main, "request_accessibility", lambda: True)
    monkeypatch.setattr(main, "Camera", _fake_camera_class())

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
    monkeypatch.setattr(main, "Camera", _fake_camera_class())
    assert main.preflight(dry_run=False, model=str(model)) == []


def test_preflight_reports_camera_that_wont_open(tmp_path, monkeypatch):
    """Camera.open() raising must surface as a tidy Error line, not a traceback.

    Without this, the spec-mandated camera check never runs, so the failure
    happens later, mid-run, as an uncaught exception instead of joining the
    other actionable problems here.
    """
    model = tmp_path / "model.task"
    model.write_bytes(b"")
    monkeypatch.setattr(main, "accessibility_granted", lambda: True)
    monkeypatch.setattr(main, "request_accessibility", lambda: True)
    monkeypatch.setattr(main, "Camera", _fake_camera_class(open_ok=False))

    problems = preflight(False, str(model))

    assert len(problems) == 1
    assert "camera" in problems[0].lower()


def test_preflight_reports_camera_that_opens_but_delivers_no_frames(tmp_path, monkeypatch):
    """An open-but-silent camera is indistinguishable from 'no hand in frame'
    unless preflight actually reads a frame and reports the difference."""
    model = tmp_path / "model.task"
    model.write_bytes(b"")
    monkeypatch.setattr(main, "accessibility_granted", lambda: True)
    monkeypatch.setattr(main, "request_accessibility", lambda: True)
    monkeypatch.setattr(main, "Camera", _fake_camera_class(read_ok=False))

    problems = preflight(False, str(model))

    assert len(problems) == 1
    assert "camera" in problems[0].lower()


def test_preflight_closes_camera_on_every_path(tmp_path, monkeypatch):
    model = tmp_path / "model.task"
    model.write_bytes(b"")
    monkeypatch.setattr(main, "accessibility_granted", lambda: True)
    monkeypatch.setattr(main, "request_accessibility", lambda: True)

    instances = []
    base = _fake_camera_class(open_ok=False)

    def factory(index=0, **kwargs):
        cam = base(index=index, **kwargs)
        instances.append(cam)
        return cam

    monkeypatch.setattr(main, "Camera", factory)
    preflight(False, str(model))

    assert len(instances) == 1
    assert instances[0].closed is True

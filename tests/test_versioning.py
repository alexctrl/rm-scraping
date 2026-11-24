import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("next_version", Path(__file__).parents[1] / "tools" / "next_version.py")
nv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nv)


def test_decide_bump():
    assert nv.decide_bump(["Fix price parsing"]) == "patch"
    assert nv.decide_bump(["Fix x", "Add image fit option"]) == "minor"
    assert nv.decide_bump(["feat(viewer): zoom"]) == "minor"
    assert nv.decide_bump(["Fix x", "refactor!: new JSON layout"]) == "major"
    assert nv.decide_bump(["Change schema\n\nBREAKING CHANGE: renamed fields"]) == "major"
    assert nv.decide_bump(["Tweak [minor]"]) == "minor"
    assert nv.decide_bump(["Address review comments"]) == "patch"  # not "Add"


def test_bump():
    assert nv.bump((1, 2, 3), "patch") == (1, 2, 4)
    assert nv.bump((1, 2, 3), "minor") == (1, 3, 0)
    assert nv.bump((1, 2, 3), "major") == (2, 0, 0)

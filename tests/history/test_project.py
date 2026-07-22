import numpy as np
from nocturne.core.image import AstroImage
from nocturne.history.project import Project
from tests.history.test_step import _Double


def _base():
    return AstroImage(np.ones((2, 2), np.float32))


def test_run_step_caches_and_advances(tmp_path):
    p = Project(_base(), str(tmp_path))
    out = p.run_step(_Double(), "x2")
    assert out.data[0, 0] == 2.0
    assert p.current().data[0, 0] == 2.0
    assert p.entries() == [("double", "x2")]


def test_undo_redo(tmp_path):
    p = Project(_base(), str(tmp_path))
    p.run_step(_Double(), "x2")
    assert p.can_undo() is True
    p.undo()
    assert p.current().data[0, 0] == 1.0
    assert p.can_redo() is True
    p.redo()
    assert p.current().data[0, 0] == 2.0


def test_before_after(tmp_path):
    p = Project(_base(), str(tmp_path))
    p.run_step(_Double(), "x2")
    before, after = p.before_after()
    assert before.data[0, 0] == 1.0
    assert after.data[0, 0] == 2.0


def test_before_after_at_base(tmp_path):
    p = Project(_base(), str(tmp_path))
    before, after = p.before_after()
    assert before.data[0, 0] == 1.0
    assert after.data[0, 0] == 1.0


def test_metadata_preserved(tmp_path):
    base = AstroImage(np.ones((2, 2), np.float32), is_linear=True, metadata={"gain": 10})
    p = Project(base, str(tmp_path))
    p.run_step(_Double(), "x2")
    p.undo()  # back to the cached base, reloaded from disk
    img = p.current()
    assert img.is_linear is True
    assert img.metadata["gain"] == 10


def test_jump_back_truncates_forward(tmp_path):
    p = Project(_base(), str(tmp_path))
    p.run_step(_Double(), "x2")   # -> 2.0
    p.run_step(_Double(), "x2")   # -> 4.0
    p.jump_back(1)                # keep only first step
    assert p.current().data[0, 0] == 2.0
    assert p.can_redo() is False
    p.run_step(_Double(), "x1")   # new branch -> 2.0
    assert p.entries() == [("double", "x2"), ("double", "x1")]


def test_set_current_metadata_persists(tmp_path):
    p = Project(_base(), str(tmp_path))
    p.set_current_metadata("k", "v")
    assert p.current().metadata["k"] == "v"


def test_state_at_is_non_destructive(tmp_path):
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.history.project import Project
    from nocturne.history.step import Step

    class _Const(Step):
        name = "X"
        def options(self): return []
        def default_option(self): return ""
        def apply(self, img, option): return AstroImage(img.data + 1, is_linear=img.is_linear)

    p = Project(AstroImage(np.zeros((4, 4), np.float32)), str(tmp_path))
    p.run_step(_Const(), "")                         # position 1, records ["X"]
    s0 = p.state_at(0)                               # read index 0
    assert float(s0.data.mean()) == 0.0
    assert len(p.entries()) == 1                     # unchanged — no truncation
    assert p.can_undo() is True

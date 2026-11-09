"""Shared test mixin: fail the test that leaked the process-wide transcode gate."""
from yt_zero_touch.core import transcode as transcode_plan


class GateFreeAfterTest:
    """Fails the test that leaked the process-wide transcode gate, by name,
    then frees it so the rest of the suite still runs.

    Deleting this guard outright would not surface a leak as a failure - the
    gate is a non-reentrant Lock, so the next test to take it would block
    forever and the suite would hang with no culprit named."""

    def tearDown(self):
        super().tearDown()
        leaked = transcode_plan._TRANSCODE_GATE.locked()
        if leaked:
            transcode_plan._TRANSCODE_GATE.release()
        self.assertFalse(leaked, "test leaked the process-wide transcode gate")

import os
import sys

# Ensure project root is on sys.path for direct test execution
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from utils.fsm import FSM, StateDef


def test_start_state_on_exit_not_called_before_enter():
    """The exit callback of the start state must not run before its first entry."""

    events = []

    def on_enter_start(fsm):
        events.append("enter")
        return "END"

    def on_exit_start(fsm):
        events.append("exit")

    states = {
        "START": StateDef("START", on_enter=on_enter_start, on_exit=on_exit_start),
        "END": StateDef("END"),
    }

    fsm = FSM(states=states, start="START", end="END")

    assert fsm.run() == "SUCCESS"
    # The exit callback should be triggered only after the entry callback
    assert events == ["enter", "exit"]


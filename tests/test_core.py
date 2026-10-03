from mailtray.core import Message, SeenState, reconcile


def msg(identifier, unread=True):
    return Message(identifier, "sender", "subject", "https://example.com", unread)


def test_initial_poll_is_silent_and_next_poll_only_reports_new_ids():
    state = SeenState()
    assert reconcile(state, [msg("old"), msg("older")]) == []
    assert reconcile(state, [msg("new"), msg("old")]) == [msg("new")]
    assert reconcile(state, [msg("new"), msg("old")]) == []


def test_read_new_message_still_notifies_and_state_survives_restart():
    state = SeenState()
    reconcile(state, [msg("old")])
    assert reconcile(state, [msg("read", False), msg("old")]) == [msg("read", False)]
    restored = SeenState.from_dict(state.to_dict())
    assert reconcile(restored, [msg("read", False), msg("old")]) == []


def test_window_rollover_does_not_renotify_known_message():
    state = SeenState()
    reconcile(state, [msg(str(i)) for i in range(50)])
    reconcile(state, [msg("incoming")])
    assert reconcile(state, [msg("0")]) == []

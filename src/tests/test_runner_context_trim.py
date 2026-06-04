"""Unit tests for Runner._select_unobserved_items.

When observational memory is active, the runner must drop items already folded
into memory.md (everything up to and including last_observed_item_id) and send
only the unobserved tail; memory.md stands in for the dropped history.

The trimmed tail must stay a valid provider request: it may not begin with a
FUNCTION_CALL_OUTPUT whose FUNCTION_CALL was cut off (e.g. an `ask_user` call
persisted during a waiting turn, its output arriving next turn).
"""

from types import SimpleNamespace

from app.domain import ItemType
from app.runtime.runner import Runner

ROOT_AGENT_ID = "agent-root"


def _msg(item_id: str):
    return SimpleNamespace(id=item_id, type=ItemType.MESSAGE, call_id=None)


def _call(item_id: str, call_id: str):
    return SimpleNamespace(id=item_id, type=ItemType.FUNCTION_CALL, call_id=call_id)


def _output(item_id: str, call_id: str):
    return SimpleNamespace(id=item_id, type=ItemType.FUNCTION_CALL_OUTPUT, call_id=call_id)


def _ctx(*, items, cursor: str | None, agent_id: str = ROOT_AGENT_ID):
    return SimpleNamespace(
        agent=SimpleNamespace(id=agent_id),
        session=SimpleNamespace(root_agent_id=ROOT_AGENT_ID, last_observed_item_id=cursor),
        items=items,
    )


# The method reads only the context (no init state), so a bare instance is enough.
_runner = Runner.__new__(Runner)


def select(ctx, *, memory_active):
    return _runner._select_unobserved_items(ctx, memory_active=memory_active)


def _ids(items):
    return [i.id for i in items]


def test_memory_inactive_keeps_all_items():
    ctx = _ctx(items=[_msg("a"), _msg("b"), _msg("c")], cursor="a")
    assert _ids(select(ctx, memory_active=False)) == ["a", "b", "c"]


def test_active_root_with_cursor_keeps_only_tail():
    ctx = _ctx(items=[_msg("a"), _msg("b"), _msg("c"), _msg("d")], cursor="b")
    assert _ids(select(ctx, memory_active=True)) == ["c", "d"]


def test_non_root_agent_keeps_all_items():
    ctx = _ctx(items=[_msg("a"), _msg("b"), _msg("c")], cursor="a", agent_id="agent-sub")
    assert _ids(select(ctx, memory_active=True)) == ["a", "b", "c"]


def test_no_cursor_keeps_all_items():
    ctx = _ctx(items=[_msg("a"), _msg("b"), _msg("c")], cursor=None)
    assert _ids(select(ctx, memory_active=True)) == ["a", "b", "c"]


def test_missing_cursor_item_keeps_all_items():
    ctx = _ctx(items=[_msg("a"), _msg("b"), _msg("c")], cursor="zzz")
    assert _ids(select(ctx, memory_active=True)) == ["a", "b", "c"]


def test_cursor_at_last_item_falls_back_to_all():
    # Empty tail would mean an inputless request — fall back to the full list.
    ctx = _ctx(items=[_msg("a"), _msg("b"), _msg("c")], cursor="c")
    assert _ids(select(ctx, memory_active=True)) == ["a", "b", "c"]


def test_orphan_ask_user_output_pulls_in_its_call():
    # ask_user call observed during a waiting turn (cursor on the call); its
    # output arrives next turn. Trim must pull the call back in, not orphan it.
    items = [_msg("u1"), _call("call1", "cid-1"), _output("out1", "cid-1"), _msg("u2")]
    ctx = _ctx(items=items, cursor="call1")
    assert _ids(select(ctx, memory_active=True)) == ["call1", "out1", "u2"]


def test_parallel_orphan_outputs_pull_in_all_calls():
    # Two tool calls before the cut, both outputs in the tail — both calls heal in.
    items = [
        _call("callA", "a"),
        _call("callB", "b"),
        _output("outA", "a"),
        _output("outB", "b"),
        _msg("u"),
    ]
    ctx = _ctx(items=items, cursor="callB")
    assert _ids(select(ctx, memory_active=True)) == ["callA", "callB", "outA", "outB", "u"]


def test_paired_call_and_output_in_tail_not_disturbed():
    items = [_msg("a"), _msg("b"), _call("c1", "x"), _output("o1", "x")]
    ctx = _ctx(items=items, cursor="b")
    assert _ids(select(ctx, memory_active=True)) == ["c1", "o1"]

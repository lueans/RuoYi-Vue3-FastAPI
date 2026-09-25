"""Node-level net impact of this task's committed canonical operations.

Only task-owned change groups are inputs. Never compare the task baseline to
the current cloud document: that would attribute collaborators' edits to AI.
Whole-node snapshots are evidence for field deltas, not replacement state.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from module_mindmap.ai.diff import IGNORED_DATA_FIELDS

CHANGE_SUMMARY_VERSION = 2
_MISSING = object()


def has_complete_change_evidence(operation_groups: list[list[dict[str, Any]]]) -> bool:  # noqa: PLR0912
    """Old rows without identities/before-images cannot promise net counts."""
    deleted: set[str] = set()
    for operations in operation_groups:
        for operation in operations:
            if not isinstance(operation, dict):
                return False
            kind = str(operation.get('type') or '')
            uid = str(operation.get('nodeUid') or operation.get('node_uid') or '')
            payload = operation.get('payload') or {}
            if not isinstance(payload, dict):
                return False
            if kind.startswith('node.') and not uid:
                return False
            if kind in {'create_node', 'update_node', 'move_node', 'delete_subtree'}:
                return False  # Raw intent lacks committed canonical evidence.
            if kind == 'node.create' and uid in deleted:
                # Old delete records lack the data needed to compare a UID
                # resurrected in a later batch with its original content.
                return False
            if kind == 'node.delete':
                if uid not in _uids(payload.get('deletedNodeUids')):
                    return False
                deleted.update(_uids(payload['deletedNodeUids']))
            if kind == 'node.update' or kind.startswith('node.tag.'):
                if kind == 'node.update' and not any(
                    isinstance(payload.get(key), bool) for key in ('dataChanged', 'childrenChanged')
                ):
                    return False
                if (payload.get('dataChanged') or kind.startswith('node.tag.')) and not all(
                    isinstance(payload.get(key), dict) for key in ('previousData', 'data')
                ):
                    return False
                if payload.get('childrenChanged') and not all(
                    isinstance(payload.get(key), list) for key in ('oldChildUids', 'childUids')
                ):
                    return False
    return True


def _apply_field_delta(projected: Any, before: Any, after: Any, *, tags: bool = False) -> Any:
    """Apply an AI field delta without adopting unchanged collaborator data."""
    if after is _MISSING:
        return _MISSING
    if isinstance(before, dict) and isinstance(after, dict) and isinstance(projected, dict):
        result = deepcopy(projected)
        for key in before.keys() | after.keys():
            old, new = before.get(key, _MISSING), after.get(key, _MISSING)
            if old == new:
                continue
            value = _apply_field_delta(result.get(key, _MISSING), old, new)
            if value is _MISSING:
                result.pop(key, None)
            else:
                result[key] = value
        return result
    if tags and all(isinstance(value, list) for value in (projected, before, after)) and all(
        isinstance(tag, dict) and tag.get('tagId') is not None
        for value in (projected, before, after) for tag in value
    ):
        original = {str(tag['tagId']): tag for tag in before}
        target = {str(tag['tagId']): tag for tag in after}
        result = {str(tag['tagId']): deepcopy(tag) for tag in projected}
        for uid in original.keys() | target.keys():
            old, new = original.get(uid, _MISSING), target.get(uid, _MISSING)
            if old == new:
                continue
            value = _apply_field_delta(result.get(uid, _MISSING), old, new)
            if value is _MISSING:
                result.pop(uid, None)
            else:
                result[uid] = value
        order = _apply_order_delta([str(tag['tagId']) for tag in projected], list(original), list(target))
        return [result[uid] for uid in order if uid in result]
    return deepcopy(after)


def _uids(value: Any) -> list[str]:
    return [str(uid) for uid in value if uid is not None and str(uid)] if isinstance(value, list) else []


def _reordered(before: list[str], after: list[str]) -> set[str]:
    shared = set(before) & set(after)
    old = [uid for uid in before if uid in shared]
    new = [uid for uid in after if uid in shared]
    ranks = {uid: index for index, uid in enumerate(new)}
    return {uid for index, uid in enumerate(old) if ranks[uid] != index}


def _apply_order_delta(projected: list[str], before: list[str], after: list[str]) -> list[str]:
    """Replay only this commit's membership/order edits, not incidental context.

    A later snapshot may contain concurrent siblings or sibling reordering.
    Replacing projected with after would incorrectly absorb those edits.
    """
    removed = set(before) - set(after)
    changed = (set(after) - set(before)) | _reordered(before, after)
    result = [uid for uid in projected if uid not in removed and uid not in changed]
    # Use gaps in the projected stable sequence, not the latest snapshot's
    # first/last UID: concurrent reordering must not shift an AI insertion
    # from the beginning of its own projection into the middle of that list.
    shared = set(before) & set(after)
    stable = [uid for uid in result if uid in shared]
    stable_uids = set(stable)
    gap = 0
    for uid in after:
        if uid in changed:
            index = result.index(stable[gap]) if gap < len(stable) else len(result)
            result.insert(index, uid)
        elif uid in stable_uids:
            gap += 1
    return result


def summarize_committed_node_changes(  # noqa: PLR0912, PLR0915
    operation_groups: list[list[dict[str, Any]]],
) -> dict[str, int]:
    """Count net changed nodes, independently of tool/canonical op counts.

    Callers must preserve commit order and deduplicate mutation groups. Added
    and deleted nodes are disjoint from updates/moves. An existing node may
    count as both updated and moved. Metadata and comments are not nodes.
    """
    existence: dict[str, list[bool]] = {}
    fields: dict[str, dict[str, list[Any]]] = {}
    opaque_updates: set[str] = set()
    initial_orders: dict[str, list[str]] = {}
    projected_orders: dict[str, list[str]] = {}
    transferred_uids: set[str] = set()
    anonymous_index = 0

    for operations in operation_groups:
        parent_changes: dict[str, tuple[list[str], list[str]]] = {}
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            kind = str(operation.get('type') or '')
            uid = str(operation.get('nodeUid') or operation.get('node_uid') or '')
            payload = operation.get('payload')
            payload = payload if isinstance(payload, dict) else {}
            # Old logs sometimes omit identity. Preserve their known count,
            # without pretending those anonymous operations can be deduped.
            if not uid:
                anonymous_index += 1
                uid = f'\x00legacy-operation:{anonymous_index}'
            if kind in {'node.create', 'create_node'}:
                existence.setdefault(uid, [False, False])[1] = True
            elif kind in {'node.delete', 'delete_subtree'}:
                for deleted in _uids(payload.get('deletedNodeUids')) or [uid]:
                    existence.setdefault(deleted, [True, True])[1] = False
            elif kind in {'node.update', 'node.tag.bind', 'node.tag.unbind', 'node.tag.reorder'}:
                if payload.get('dataChanged') is True or kind.startswith('node.tag.'):
                    previous, current = payload.get('previousData'), payload.get('data')
                    if not isinstance(previous, dict) or not isinstance(current, dict):
                        opaque_updates.add(uid)
                    else:
                        changes = fields.setdefault(uid, {})
                        for key in set(previous) | set(current):
                            if key == 'uid' or key in IGNORED_DATA_FIELDS:
                                continue
                            old, new = previous.get(key, _MISSING), current.get(key, _MISSING)
                            if key == 'tag':
                                old = [] if old is _MISSING else old
                                new = [] if new is _MISSING else new
                            if old != new:
                                state = changes.setdefault(key, [old, old])
                                state[1] = _apply_field_delta(state[1], old, new, tags=key == 'tag')
                if payload.get('childrenChanged') is True:
                    before = _uids(payload.get('oldChildUids'))
                    after = _uids(payload.get('childUids'))
                    if uid in parent_changes:
                        parent_changes[uid] = (parent_changes[uid][0], after)
                    else:
                        parent_changes[uid] = (before, after)

        # Initialize all parents before replaying this atomic group, so a
        # cross-parent move has both its source and destination represented.
        before_parents = {}
        after_parents = {}
        for parent, (before, after) in parent_changes.items():
            # A collaborator may move a known node into a parent first seen
            # later. That snapshot must not redefine its original AI parent.
            if parent not in initial_orders:
                known = {uid for children in initial_orders.values() for uid in children}
                initial_orders[parent] = [uid for uid in before if uid not in known]
            if parent not in projected_orders:
                known = {uid for children in projected_orders.values() for uid in children}
                projected_orders[parent] = [uid for uid in before if uid not in known]
            before_parents.update(dict.fromkeys(before, parent))
            after_parents.update(dict.fromkeys(after, parent))
        transfers = {
            uid for uid in before_parents.keys() | after_parents.keys()
            if before_parents.get(uid) != after_parents.get(uid)
        }
        # Apply membership transfers to the UID's projected owner, not just
        # the current cloud source parent (which can have changed externally).
        for parent, children in projected_orders.items():
            projected_orders[parent] = [
                uid for uid in children
                if uid not in transfers or after_parents.get(uid) == parent
            ]
        transferred_uids.update(transfers)
        for parent, (before, after) in parent_changes.items():
            projected_orders[parent] = _apply_order_delta(projected_orders[parent], before, after)

    added = {uid for uid, (before, after) in existence.items() if not before and after}
    deleted = {uid for uid, (before, after) in existence.items() if before and not after}
    # Also exclude nodes created and then removed in this task.
    non_shared = {uid for uid, (before, after) in existence.items() if not before or not after}
    updated = opaque_updates | {
        uid for uid, changes in fields.items()
        if any(old != new for old, new in changes.values())
    }
    old_parents = {
        uid: parent for parent, children in initial_orders.items()
        for uid in children if uid not in non_shared
    }
    new_parents = {
        uid: parent for parent, children in projected_orders.items()
        for uid in children if uid not in non_shared
    }
    moved = {
        uid for uid in transferred_uids - non_shared
        if old_parents.get(uid) != new_parents.get(uid)
    }
    for parent, before in initial_orders.items():
        stable = {
            uid for uid in before
            if uid in old_parents and old_parents.get(uid) == new_parents.get(uid)
        }
        moved.update(_reordered(
            [uid for uid in before if uid in stable],
            [uid for uid in projected_orders[parent] if uid in stable],
        ))
    result = {
        'added': len(added), 'updated': len(updated - non_shared),
        'moved': len(moved), 'deleted': len(deleted),
    }
    result['total'] = sum(result.values())
    return result

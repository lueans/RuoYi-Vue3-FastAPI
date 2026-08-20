from typing import Literal

MindmapAction = Literal['list', 'query', 'add', 'edit', 'remove']


def mindmap_permissions(action: MindmapAction) -> list[str]:
    """Return current and legacy permission names for one file action.

    The resource-qualified namespace avoids collisions with tag/folder/template
    permissions. Legacy aliases keep upgraded servers compatible with existing
    role assignments until the optional database migration is applied.
    """
    return [f'mindmap:mindmap:{action}', f'mindmap:{action}']

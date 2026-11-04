"""Bounded workspace response for object and pixel review clients."""
from urllib.parse import parse_qs, urlparse

import class_sets
import review_evidence
import review_masks


def workspace(store, path, project, links, token):
    query = parse_qs(urlparse(path).query, strict_parsing=True, keep_blank_values=True)
    if set(query) - {'limit', 'offset', 'lane', 'status', 'around', 'after', 'source_session', 'folder_id'} or any(len(v) != 1 for v in query.values()):
        raise ValueError('invalid workspace page request')
    page = store.frame_page(**{key: int(values[0]) if key in ('limit', 'offset', 'around', 'after') else values[0]
                               for key, values in query.items()})
    page['context'].update(workspace={'id': project,
        'label': review_evidence.metadata(store, 'workspace_label') or '현재 작업공간'}, workspaces=links or [])
    object_set = class_sets.object_set(store)
    return {**page, 'classes': [c['name'] for c in object_set['classes']],
            'object_class_set': object_set,
            'workspace_kind': review_evidence.metadata(store, 'workspace_kind'),
            'token': token, 'exports': store.exports(), 'segmentation_supported': True,
            'pixel_classes': review_masks.served_classes(store),
            'map_reference': review_evidence.map_reference(store)}

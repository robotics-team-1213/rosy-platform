"""Source-cluster diagnostics; empirical intervals never admit a model."""
from collections import defaultdict
import random

import numpy as np

from road_fitness import _summarize

RESAMPLES, SEED = 1000, 0
METRICS = ('iou', 'outside_false_positive_rate', 'missed_fraction',
           'full_grid_pixel_coverage', 'frame_coverage')


def _source_summary(rows):
    rows = sorted(rows, key=lambda r: r['identity'])
    groups = defaultdict(list)
    for row in rows:
        groups[row['capture_group']].append(row)
    sources = {key: _summarize(groups[key]) for key in sorted(groups)}
    intervals = {}
    # One source contributes all of its frames together, including abstentions.
    rng = random.Random(SEED)
    draws = {target: np.empty((RESAMPLES, 9)) for target in ('road_surface', 'current_region')}
    matrices = {}
    for target in draws:
        matrices[target] = np.array([
            [s[target]['true_positive_pixels'], s[target]['false_positive_pixels'],
             s[target]['false_negative_pixels'], s[target]['scored_outside_truth_pixels'],
             s[target]['scored_truth_pixels'], s[target]['scored_pixels'],
             s[target]['valid_truth_pixels'] + s[target]['roi_excluded_valid_truth_pixels'],
             s[target]['scored_frames'], s['frames']] for s in sources.values()], dtype=float)
    if len(sources) >= 2:
        for index in range(RESAMPLES):
            selected = rng.choices(range(len(sources)), k=len(sources))
            for target in draws:
                draws[target][index] = matrices[target][selected].sum(axis=0)
    for target, values in draws.items():
        intervals[target] = {}
        for name, numerator, denominator in (
                ('iou', 0, (0, 1, 2)), ('outside_false_positive_rate', 1, (3,)),
                ('missed_fraction', 2, (4,)), ('full_grid_pixel_coverage', 5, (6,)),
                ('frame_coverage', 7, (8,))):
            bounds, valid, reason = None, 0, 'insufficient_sources'
            if len(sources) >= 2:
                total = values[:, denominator].sum(axis=1)
                valid = int((total > 0).sum())
                reason = 'ok' if valid == RESAMPLES else 'undefined_resamples'
                if valid == RESAMPLES:
                    bounds = np.percentile(values[:, numerator] / total, [2.5, 97.5], method='linear').tolist()
            intervals[target][name] = {'bounds': bounds, 'valid_resamples': valid, 'reason': reason}
    return {'source_count': len(sources), 'sources': sources, 'point': _summarize(rows),
            'intervals': intervals}


def summarize_sources(reports):
    """Use bound capture groups, never frame independence or mixed domains."""
    rows = list(reports)
    identities, sessions, domains = set(), {}, {}
    for row in rows:
        for field in ('identity', 'session', 'capture_group'):
            value = row.get(field)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError('exact frame identity, session and capture group required')
        identity, session, group, domain = (row[k] for k in ('identity', 'session', 'capture_group', 'domain'))
        if identity in identities or domain not in ('real', 'simulation'):
            raise ValueError('duplicate frame identity or invalid domain')
        if session in sessions and sessions[session] != group:
            raise ValueError('session belongs to multiple capture groups')
        if group in domains and domains[group] != domain:
            raise ValueError('capture group belongs to multiple domains')
        identities.add(identity)
        sessions[session], domains[group] = group, domain
    by_domain, by_condition = {}, {}
    for domain in ('real', 'simulation'):
        selected = [r for r in rows if r['domain'] == domain]
        by_domain[domain] = _source_summary(selected)
        by_condition[domain] = {c: _source_summary([r for r in selected if c in r['conditions']])
                                for c in sorted({c for r in selected for c in r['conditions']})}
    return {'method': 'capture-group-percentile-bootstrap/1', 'resamples': RESAMPLES, 'seed': SEED,
            'confidence_level': .95, 'metrics': list(METRICS), 'domains': by_domain,
            'conditions': by_condition, 'fitness_verdict': 'HOLD'}

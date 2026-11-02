"""One strict, whole-file G1 timing job shared by CI and lab selection."""
import re

TARGET = 'test/test_platform_g1_timing.py'
ALONE = 'ROSY_JOB_ALONE=1'
PLUGIN = '-ptools.g1_timing_gate'
DEDICATED = [ALONE, TARGET, '-pno:xdist', PLUGIN]
ENV = re.compile(r'^ROSY_[A-Z0-9_]*=')
RECEIPT = re.compile(r'^\[g1-timing-gate\] expected=(\d+) collected=(\d+) passed=(\d+) skipped=(\d+) clean=(\d+)$', re.M)


def split_environment(words):
    environment, paths = {}, list(words)
    while paths and ENV.match(paths[0]):
        key, value = paths.pop(0).split('=', 1)
        environment[key] = value
    return paths, environment


def omit(invocations, skip):
    required = any(covers(w) for inv in invocations for w in inv)
    result = [[w for w in inv if w not in skip] for inv in invocations]
    result = [inv for inv in result if inv]
    validate(result, required)
    return result


def affected_invocations(selection, skip):
    """Selection JSON follows the same local/full convention as affected --run."""
    return omit(selection['local_invocations' if selection['mode'] == 'full' else 'invocations'], skip)


def covers(word):
    path = word.replace('\\', '/').removeprefix('./').split('::', 1)[0].rstrip('/')
    return not word.startswith('-') and not ENV.match(word) and (
        path == TARGET or path in ('', '.') or TARGET.startswith(path + '/'))


def dedicated(inv):
    return any(w.split('::', 1)[0] == TARGET for w in inv) and (ALONE in inv or PLUGIN in inv)


def validate(invocations, required):
    jobs = [inv for inv in invocations if dedicated(inv)]
    if len(jobs) != int(required) or any(inv != DEDICATED for inv in jobs):
        raise ValueError('G1 timing requires exactly one whole-file exclusive serial job')
    for inv in invocations:
        if inv in jobs:
            continue
        if any(w.split('::', 1)[0] == TARGET for w in inv):
            raise ValueError('G1 timing file also appears in an ordinary invocation')
        if required and any(covers(w) for w in inv) and '--ignore=' + TARGET not in inv:
            raise ValueError('ordinary invocation still collects G1 timing')
        if not any(not w.startswith('-') and not ENV.match(w) for w in inv):
            raise ValueError('empty ordinary invocation would collect the entire repository')


def separate(invocations, available=True):
    ordinary, needed = [], False
    for original in invocations:
        inv = list(original)
        selected = any(w.split('::', 1)[0] == TARGET or available and covers(w) for w in inv)
        needed |= selected
        if dedicated(inv):
            if inv != DEDICATED:
                raise ValueError('malformed G1 timing exclusive invocation')
            continue
        inv = [w for w in inv if w.split('::', 1)[0] != TARGET]
        if any(covers(w) for w in inv) and selected and '--ignore=' + TARGET not in inv:
            inv.append('--ignore=' + TARGET)
        if any(not w.startswith('-') and not ENV.match(w) for w in inv):
            ordinary.append(inv)
    result = ordinary + [list(DEDICATED)] if needed else ordinary
    validate(result, needed)
    return result


def matrix(entries, available):
    result, needed = [], False
    for entry in entries:
        if entry.get('kind') == 'smoke':
            result.append(entry)
            continue
        invocations = separate(entry['invocations'], available)
        needed |= any(dedicated(inv) for inv in invocations)
        ordinary = [inv for inv in invocations if not dedicated(inv)]
        if ordinary:
            result.append({**entry, 'invocations': ordinary})
    if needed:
        result.append({'name': 'g1-timing-exclusive', 'kind': 'pytest', 'gating': True,
                       'ros': 'overlay', 'invocations': [list(DEDICATED)]})
    validate([inv for entry in result for inv in entry['invocations']], needed)
    return result


def evidence(log, code=None):
    if code is not None and code != 0:
        return f'G1 timing exclusive job exited {code}; no retry'
    try:
        text = log.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return 'G1 timing receipt missing; no retry'
    rows = RECEIPT.findall(text)
    if len(rows) != 1:
        return 'G1 timing requires exactly one complete receipt; no retry'
    expected, collected, passed, skipped, clean = map(int, rows[0])
    if not expected or expected != collected or expected != passed or skipped or clean != 1:
        return 'G1 timing incomplete, failed or skipped; no retry'
    summaries = re.findall(r'(?m)^.*\b\d+ passed.*\bin [0-9.]+s', text)
    if len(summaries) != 1 or re.search(r'\b\d+ (?:failed|skipped|errors?)\b', summaries[0]):
        return 'G1 timing summary is missing, repeated or nonclean; no retry'
    if int(re.search(r'(\d+) passed', summaries[0])[1]) != expected:
        return 'G1 timing summary differs from the whole-file receipt; no retry'
    return None

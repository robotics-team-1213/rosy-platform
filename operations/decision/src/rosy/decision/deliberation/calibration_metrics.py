"""Pure offline categorical metrics; no samples, network, or execution authority."""
import hashlib
import json
import math
from statistics import NormalDist


def serialize(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(serialize(value).encode()).hexdigest()


def finite(value, *, maximum=None):
    if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
            or maximum is not None and value > maximum):
        raise ValueError('invalid finite calibration metric')
    return value


def wilson_lower(correct, count):
    """Pointwise one-sided 95% score bound, z=NormalDist().inv_cdf(.95)."""
    if type(correct) is not int or type(count) is not int or not 0 <= correct <= count:
        raise ValueError('invalid Wilson counts')
    if not count:
        return 0.0
    z = NormalDist().inv_cdf(.95)
    p = correct / count
    return max(0.0, (p + z*z/(2*count) - z*math.sqrt(p*(1-p)/count + z*z/(4*count*count))) / (1 + z*z/count))


def probabilities(values, choices):
    if type(values) not in (list, tuple) or len(values) != len(choices):
        raise ValueError('invalid calibration probability collection')
    result = {}
    for value in values:
        if (type(value) is not dict or set(value) != {'choice', 'probability'}
                or type(value['choice']) is not str or value['choice'] not in choices
                or value['choice'] in result):
            raise ValueError('invalid calibration choice')
        result[value['choice']] = finite(value['probability'], maximum=1)
    if abs(math.fsum(result.values()) - 1) > 1e-6:
        raise ValueError('invalid calibration probability sum')
    return result


def top(values):
    ranked = sorted(values.items(), key=lambda item: item[1], reverse=True)
    return ranked[0][0], ranked[0][1], ranked[0][1] - ranked[1][1]


def group_key(values):
    choice, score, _ = top(values)
    return choice, min(9, int(score * 10))


def metrics(rows, choices):
    grouped = {(choice, index): [] for choice in choices for index in range(10)}
    brier, correct, forbidden = 0.0, 0, 0
    for row in rows:
        values = probabilities(row['alternatives'], choices)
        choice, score, gap = top(values)
        hit = int(not row['abstained'] and gap > 0 and choice == row['expected'])
        correct += hit
        brier += math.fsum((value - int(key == row['expected']))**2 for key, value in values.items())
        grouped[group_key(values)].append((score, hit))
        forbidden += int(any(row[field] for field in
            ('unsafe_error', 'binding_error', 'unnecessary_effect', 'required_abstain_error')))
    bins, ece = [], 0.0
    for (choice, index), samples in grouped.items():
        count, hits = len(samples), sum(hit for _, hit in samples)
        mean = math.fsum(score for score, _ in samples) / count if count else None
        accuracy = hits / count if count else None
        if count:
            ece += count / len(rows) * abs(mean - accuracy)
        bins.append(dict(choice=choice, index=index, count=count, correct=hits,
                         mean_raw_probability=mean, empirical_accuracy=accuracy,
                         accuracy_lower=wilson_lower(hits, count)))
    latencies = sorted(row['latency_ms'] for row in rows)
    return dict(count=len(rows), correct=correct, accuracy=correct/len(rows),
                accuracy_lower=wilson_lower(correct, len(rows)), brier=brier/len(rows), ece=ece,
                forbidden=forbidden, p95_latency_ms=latencies[math.ceil(.95*len(rows))-1]), bins

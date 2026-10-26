"""Deterministic, grouped and label-purged chronological research partitions."""
import math


def temporal_partition(events, label_ends, train_fraction=.7):
    """Never split a signature or timestamp; training labels precede test signals.

    Choose the last legal boundary at or before the original fraction target.
    Missing outcomes are excluded after choosing that boundary. Purged training
    observations never migrate into test. Exact exit quote times include any
    provider/quote delay represented in the supplied historical observations.
    """
    if (not isinstance(train_fraction, (int, float)) or isinstance(train_fraction, bool)
            or not math.isfinite(train_fraction) or not 0 < train_fraction < 1):
        raise ValueError('Invalid chronological train fraction')
    for event in events:
        if (len(event) != 5 or type(event[0]) is not int or event[0] < 0
                or not isinstance(event[1], str) or not event[1]
                or not isinstance(event[3], str) or not event[3]):
            raise ValueError('Invalid temporal event identity/date')
    if len({event[3] for event in events}) != len(events):
        raise ValueError('Duplicate temporal mint identity')
    ordered = sorted(events, key=lambda e: (e[0], e[1], str(e[2]), e[3], str(e[4])))
    last = {event[1]: index for index, event in enumerate(ordered)}
    target = int(len(ordered) * train_fraction)
    cut = reach = 0
    for index, event in enumerate(ordered[:-1]):
        reach = max(reach, last[event[1]])
        candidate = index + 1
        if candidate <= target and index >= reach and event[0] < ordered[candidate][0]:
            cut = candidate
    test_start = ordered[cut][0] if ordered else None
    train, test, purged = [], [], 0
    for index, event in enumerate(ordered):
        end = label_ends.get(event[3])
        if end is None:
            continue
        if type(end) is not int or end < event[0]:
            raise ValueError('Invalid training label availability time')
        if index >= cut:
            test.append(event)
        elif end < test_start:
            train.append(event)
        else:
            purged += 1
    diagnostics = {
        'policy': 'signature_timestamp_groups_label_purge_v1',
        'target_train_events': target, 'boundary_train_events': cut,
        'test_period_started_at': test_start, 'purged_train_observations': purged,
        'train_label_available_before': test_start,
        'max_train_label_time': max((label_ends[e[3]] for e in train), default=None),
        'boundary_available': bool(cut),
    }
    return train, test, diagnostics

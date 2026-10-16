"""Stable suite pair counts and deterministic batch slicing helpers."""

PAIR_COUNTS = {"banking": (16, 9), "workspace": (40, 6), "slack": (21, 5), "travel": (20, 7)}


def pair_batch(user_tasks, injection_tasks, *, offset: int = 0, batch_size: int = 5):
    pairs = [(user, injection) for user in user_tasks for injection in injection_tasks]
    # Start each batch with varied injections while retaining a deterministic order.
    pairs.sort(key=lambda pair: (str(getattr(pair[1], "id", "")), str(getattr(pair[0], "id", ""))))
    return pairs[max(offset, 0):max(offset, 0) + min(max(batch_size, 1), 5)]

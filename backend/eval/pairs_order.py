"""Curated first-batch task and attack priorities for informative eval runs."""

PRIORITY = {
    ("B2", "inj_bank_1", "task_disguise"): 0,
    ("B8", "inj_bank_3", "obfuscated"): 1,
    ("X1", "inj_cross_1", "direct"): 2,
    ("S8", "inj_out_1", "markdown_exfil"): 3,
    ("E1", "inj_mail_1", "ignore_previous"): 4,
}


def priority(pair: tuple[str, str, str]) -> tuple[int, str, str, str]:
    return (PRIORITY.get(pair, 100), *pair)

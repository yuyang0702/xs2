"""Finite startup budgets for workers sharing one initialization lease."""


def executor_boot_timeout(count: int) -> float:
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 32:
        raise ValueError('Workflow Executor count must be between 1 and 32')
    # Imports can overlap, but each member initializes shared state in turn.
    return 60.0 * count


def server_readiness_timeout(count: int) -> float:
    # Leave the controller time for imports, recovery and final readiness.
    return max(180.0, executor_boot_timeout(count) + 60.0)

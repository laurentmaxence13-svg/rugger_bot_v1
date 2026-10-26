"""In-process scanner refusal latch and shared cancellation-safe supervision."""
import asyncio


class ScannerHealth:
    """One supervision lifetime. A failure can never be reset by a SQL refresh."""
    def __init__(self):
        self._failed = False
        self.failures = []
        self.failure_event = asyncio.Event()
        self.tasks = []

    @property
    def failed(self):
        return self._failed

    def fail(self, stage, error=None):
        self._failed = True
        if error is not None and not any(error is e for _, e in self.failures):
            self.failures.append((stage, error))
            self.failure_event.set()

    def start_task(self, coroutine, name):
        started = False
        async def monitored():
            nonlocal started
            started = True
            try:
                result = await coroutine
            except BaseException as error:
                self.fail(name, error)  # Synchronous: before any outer cleanup await.
                raise
            else:
                self.fail(name)
                return result
        wrapper = monitored()
        try:
            task = asyncio.create_task(wrapper, name=name)
        except BaseException:
            wrapper.close()
            coroutine.close()
            self.fail(name)
            raise
        def release_unstarted(task):
            if not started:
                coroutine.close()
        task.add_done_callback(release_unstarted)
        self.tasks.append(task)
        return task

    def permits_entries(self):
        if self.failed or not self.tasks:
            return False
        for task in self.tasks:
            if task.done() or task.cancelling():
                self.fail(f'scanner task stopped: {task.get_name()}')
                return False
        return True

    def append_errors(self, failures):
        for stage, error in self.failures:
            # Peer cancellation requested during shutdown is not a new primary.
            if not isinstance(error, (asyncio.CancelledError, GeneratorExit)) and not any(error is e for _, e in failures):
                failures.append((stage, error))


def _raise_paper_failures(failures):
    """Keep the original exception (and cancellation) with staged diagnostics.

    Python 3.10 is supported: ExceptionGroup/add_note are not required.
    """
    if not failures:
        return
    primary = failures[0][1]
    if not isinstance(primary, asyncio.CancelledError):
        # Only an actual cancellation of the caller supersedes its operation
        # error. A resource may itself raise CancelledError while closing.
        primary = next((exc for stage, exc in failures
                        if stage == 'cleanup cancellation'
                        and isinstance(exc, asyncio.CancelledError)), primary)
    diagnostics = list(failures)
    for _, error in failures:
        for stage, nested in getattr(error, 'paper_failures', ()):
            if not any(stage == s and nested is e for s, e in diagnostics):
                diagnostics.append((stage, nested))
    primary.paper_failures = tuple(diagnostics)
    if hasattr(primary, 'add_note'):
        for stage, exc in diagnostics:
            note = f'PAPER {stage}: {type(exc).__name__}: {exc}'
            if note not in getattr(primary, '__notes__', ()):
                primary.add_note(note)
    elif any(error is not primary for _, error in diagnostics):
        # Python 3.10: expose secondary failures in the native traceback too.
        detail = RuntimeError('; '.join(
            f'PAPER {stage}: {type(error).__name__}: {error}'
            for stage, error in diagnostics if error is not primary))
        detail.__cause__ = primary.__cause__
        raise primary from detail
    raise primary


async def _await_paper_cleanup(cleanup, failures):
    """Finish owned cleanup despite repeated cancellation of the caller."""
    caller = asyncio.current_task()
    cancellation_count = caller.cancelling()
    task = asyncio.create_task(cleanup, name='paper-resource-cleanup')
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            current_count = caller.cancelling()
            if current_count > cancellation_count:
                failures.append(('cleanup cancellation', exc))
            elif task.cancelled():
                break  # Retrieve the child's own cancellation below.
            else:
                failures.append(('cleanup wait', exc))
            cancellation_count = current_count
        except BaseException:
            break  # Retrieve the cleanup error below, without losing the caller's.
    try:
        task.result()
    except BaseException as exc:
        failures.append(('cleanup', exc))


async def _stop_supervised_tasks(tasks, timeout=5.0, *, observed=()):
    if not tasks:
        return
    for task in tasks:
        if not task.done():
            task.cancel()
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    failures = []
    for task in tasks:  # Deterministic acquisition order, not set iteration order.
        if task not in done:
            continue
        try:
            task.result()
        except asyncio.CancelledError as exc:
            # A requested cancellation is normal; its cleanup errors are not.
            failures.extend((stage, error) for stage, error in getattr(exc, 'paper_failures', ())
                            if not isinstance(error, asyncio.CancelledError))
        except BaseException as exc:
            if exc not in observed:
                failures.append((f'supervised task {task.get_name()}', exc))
    if pending:
        def diagnose_late_failure(task):
            try:
                task.result()
            except asyncio.CancelledError as exc:
                for stage, error in getattr(exc, 'paper_failures', ()):
                    if not isinstance(error, asyncio.CancelledError):
                        task.get_loop().call_exception_handler({
                            'message': f'PAPER late supervised cleanup failure: {stage}',
                            'exception': error, 'task': task,
                        })
            except BaseException as exc:
                task.get_loop().call_exception_handler({
                    'message': 'PAPER supervised task failed after cleanup timeout',
                    'exception': exc, 'task': task,
                })
        for task in pending:
            task.cancel()
            task.add_done_callback(diagnose_late_failure)
        failures.append(('supervised timeout', RuntimeError(
            'Nettoyage asyncio incomplet apres delai limite: ' +
            ', '.join(sorted(task.get_name() for task in pending)))))
    _raise_paper_failures(failures)

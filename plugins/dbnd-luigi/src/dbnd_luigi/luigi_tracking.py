import logging

from typing import Optional

import luigi
import luigi.scheduler
import luigi.worker

from luigi.interface import _WorkerSchedulerFactory

from dbnd_luigi.luigi_handlers import LuigiEventsHandler
from dbnd_luigi.luigi_run_manager import LuigiRunManager


logger = logging.getLogger(__name__)

# Singleton
lrm: Optional[LuigiRunManager] = LuigiRunManager()
handler: Optional[LuigiEventsHandler] = None


def register_luigi_tracking():
    global lrm
    global handler

    if lrm.active:
        lrm = LuigiRunManager()

    if handler is None:
        handler = LuigiEventsHandler()

    handler.set_run_manager(lrm)
    register(handler)
    lrm.active = True


def register(handler):
    luigi.Task.event_handler(luigi.Event.START)(handler.on_run_start)
    luigi.Task.event_handler(luigi.Event.SUCCESS)(handler.on_success)
    luigi.Task.event_handler(luigi.Event.FAILURE)(handler.on_failure)
    luigi.Task.event_handler(luigi.Event.DEPENDENCY_DISCOVERED)(
        handler.on_dependency_discovered
    )
    luigi.Task.event_handler(luigi.Event.DEPENDENCY_MISSING)(
        handler.on_dependency_missing
    )
    luigi.Task.event_handler(luigi.Event.DEPENDENCY_PRESENT)(
        handler.on_dependency_present
    )


class _DbndWorkerSchedulerFactory(_WorkerSchedulerFactory):
    def create_worker(self, scheduler, worker_processes, assistant=False):
        return _DbndWorker(
            scheduler=scheduler, worker_processes=worker_processes, assistant=assistant
        )


class _DbndWorker(luigi.worker.Worker):
    def run(self):
        # Passing currently scheduled tasks just in case we are running an orphaned task and need a root task template
        lrm.init_databand_run(self._scheduled_tasks)
        """
        _init_databand_run is called right before worker.run executes.
        Worker.run() when working in multiprocess calls `fork()`.
        Our best method of supplying the databand run object to all subsequent subprocesses is initializing it before
        the worker processes split.
        """
        return super(_DbndWorker, self).run()


def _set_luigi_kwargs(kwargs):
    kwargs.setdefault("worker_scheduler_factory", _DbndWorkerSchedulerFactory())
    kwargs.setdefault("detailed_summary", True)
    kwargs.setdefault("local_scheduler", True)
    return kwargs


def dbnd_luigi_run(**kwargs):
    """entry point to cmd run"""
    register_luigi_tracking()
    kwargs = _set_luigi_kwargs(kwargs)
    run_result = luigi.run(**kwargs)  # this is deprecated, should consider change it
    return run_result


def dbnd_luigi_build(tasks, **kwargs):
    """entry point for python run"""
    register_luigi_tracking()
    kwargs = _set_luigi_kwargs(kwargs)
    run_result = luigi.build(tasks=tasks, **kwargs)
    return run_result

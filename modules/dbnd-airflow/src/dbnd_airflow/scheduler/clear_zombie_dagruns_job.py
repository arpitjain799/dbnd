import datetime
import logging

from airflow.jobs import BackfillJob, BaseJob
from airflow.utils import timezone
from airflow.utils.db import provide_session

from dbnd_airflow.scheduler.zombies import find_and_kill_dagrun_zombies


class ClearZombieJob(BaseJob):
    ID_PREFIX = BackfillJob.ID_PREFIX + "manual_    "
    ID_FORMAT_PREFIX = ID_PREFIX + "{0}"
    __mapper_args__ = {"polymorphic_identity": "BackfillJob"}
    TYPE = "ZombieJob"
    TIME_BETWEEN_RUNS = 60 * 5

    def __init__(self, *args, **kwargs):
        super(ClearZombieJob, self).__init__(*args, **kwargs)
        # Trick for distinguishing this job from other backfills
        self.executor_class = self.TYPE

    @provide_session
    def _execute(self, session=None):
        last_run_date = (
            session.query(ClearZombieJob.latest_heartbeat)
            .filter(ClearZombieJob.executor_class == self.TYPE)
            .order_by(ClearZombieJob.end_date.asc())
            .first()
        )
        if (
            last_run_date
            and last_run_date[0] + datetime.timedelta(seconds=self.TIME_BETWEEN_RUNS)
            > timezone.utcnow()
        ):
            # If we cleaned zombies recently we can do nothing
            return
        try:
            find_and_kill_dagrun_zombies(None, session=session)
        except Exception as err:
            # Fail silently as this is not crucial process
            session.rollback()
            logging.warning("Cleaning zombies failed: %s", err)

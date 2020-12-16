from pytest import fixture

from dbnd import task
from dbnd.testing.helpers_pytest import assert_run_task
from dbnd_test_scenarios.test_common.targets.target_test_base import TargetTestBase


@task
def task_that_spawns(value=1.0):
    # type: (float)-> float

    value_task = task_that_runs_inline.task(value=value)
    value_task.dbnd_run()

    return value_task.result.read_pickle() + 0.1


@task
def task_that_runs_inline(value=1.0):
    # type: (float)-> float
    return value + 0.1


class TestInlineSpawnCalls(TargetTestBase):
    @fixture
    def target_1_2(self):
        t = self.target("file.txt")
        t.as_object.writelines(["1", "2"])
        return t

    def test_inline_call(self, target_1_2):
        assert_run_task(task_that_spawns.t())

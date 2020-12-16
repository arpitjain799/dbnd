import logging

from dbnd import ParameterScope, PipelineTask, data, dbnd_run_cmd, output, parameter
from dbnd._core.context.databand_context import new_dbnd_context
from dbnd.tasks.basics import SimplestTask
from dbnd.testing.helpers_pytest import assert_run_task
from dbnd_test_scenarios.test_common.task.factories import TTask, TTaskWithInput
from test_dbnd.scenarios.pipelines.pipe_4tasks import (
    MainPipeline as Scenario4_MainPipeline,
)


logger = logging.getLogger(__name__)


class TestTaskRun(object):
    def test_ttask(self):
        task = TTask()
        assert_run_task(task)

    def test_task_require(self):
        class A(TTask):
            pass

        class B(A):
            x = parameter[str]
            tt = data

            def _requires(self):
                return A(
                    task_name="required_by_B"
                )  # This will end up referring to the same object

        task_A = A(task_name="A_wired_B")
        task_B = B(task_name="B_task_B", tt=task_A, x="d")
        task_B.dbnd_run()
        assert task_B._complete()
        assert task_B.tt["t_output"].task._complete()
        assert task_A._complete()

    def test_simple_pipeline(self):
        class A(TTask):
            pass

        class B(A):
            x = parameter[str]
            tt = data

            o_first = output.data
            o_second = output.data

            def run(self):
                super(B, self).run()
                self.o_first.as_object.touch()
                self.o_second.as_object.touch()

        class CPipeline(PipelineTask):
            x = parameter[str]

            a_output = output.data
            b_main = output.data
            b_output = output.data

            def band(self):
                self.a_output = A(task_name="A_simple")
                b_main = B(task_name="B_simple", tt=self.a_output, x=self.x)

                self.b_main = b_main
                self.b_output = b_main.o_second

        c_pipeline = CPipeline(x="some_x_values")
        c_pipeline.dbnd_run()
        assert c_pipeline
        assert c_pipeline.a_output["t_output"].source_task._complete()
        assert c_pipeline.b_main["o_second"].source_task._complete()
        assert c_pipeline.b_output.source_task._complete()

    def test_nested_pipeline(self):
        class A(TTask):
            tt = data
            x = parameter[str]

        class BPipeline(PipelineTask):
            tt = data(scope=ParameterScope.children)
            x = parameter(scope=ParameterScope.children)[str]

            some_a = output

            def band(self):
                self.some_a = A(task_name="A_%s" % self.x)

        class CPipeline(PipelineTask):
            tt = data(scope=ParameterScope.children)

            task_p1 = output
            some_a = output

            def band(self):
                self.task_p1 = BPipeline(task_name="B_x10", x=10)
                self.some_a = BPipeline(task_name="B_x20", x=20).some_a

        c_pipeline = CPipeline(tt=__file__)
        c_pipeline.dbnd_run()
        assert c_pipeline
        assert c_pipeline.task_p1["some_a"]["t_output"].source_task._complete()
        assert c_pipeline.some_a["t_output"].source_task._complete()
        assert isinstance(c_pipeline.some_a["t_output"].source_task, A)

    def test_foreign_context_should_not_fail(self):
        with new_dbnd_context():
            t = SimplestTask()
            t.dbnd_run()

        TTaskWithInput(t_input=t).dbnd_run()

    def test_scenario_4_select_task(self, tmpdir_factory):
        dbnd_run_cmd([Scenario4_MainPipeline.get_task_family(), "-c run.task=B_F4Task"])

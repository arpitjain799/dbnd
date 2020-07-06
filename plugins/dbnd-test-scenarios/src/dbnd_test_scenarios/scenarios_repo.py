import logging

from dbnd._core.utils.project.project_fs import abs_join, relative_path
from targets import target


logger = logging.getLogger(__name__)
_PLUGIN_ROOT = relative_path(__file__, "..", "..")
_PLUGIN_SRC_ROOT = relative_path(__file__)


def scenario_root_path(*path):
    return abs_join(_PLUGIN_ROOT, *path)


def scenario_src_path(*path):
    return abs_join(_PLUGIN_SRC_ROOT, *path)


def test_scenario_path(*path):
    return scenario_root_path("scenarios", *path)


def test_scenario_target(*path):
    return target(test_scenario_path(*path))


def scenario_data_path(*path):
    return scenario_root_path("data", *path)


def scenario_data_target(*path):
    return target(scenario_data_path(*path))


def scenario_pyspark_path(*path):
    return scenario_src_path("spark", "pyspark_scripts", *path)


class Scenarios(object):
    pass


scenarios = Scenarios()

# © Copyright Databand.ai, an IBM Company 2022

import logging

from collections import OrderedDict
from typing import Any, ContextManager, Dict, Optional

from dbnd._core.utils.basics.load_python_module import load_python_callable
from dbnd._core.utils.type_check_utils import is_instance_by_class_name
from dbnd_airflow.tracking.dbnd_spark_conf import (
    track_databricks_submit_run_operator,
    track_dataproc_pyspark_operator,
    track_dataproc_submit_job_operator,
    track_ecs_operator,
    track_emr_add_steps_operator,
    track_spark_submit_operator,
)


logger = logging.getLogger(__name__)

# registering operators names to the relevant tracking method
_EXECUTE_TRACKING = OrderedDict(
    {
        ("EmrAddStepsOperator", track_emr_add_steps_operator),
        ("DatabricksSubmitRunOperator", track_databricks_submit_run_operator),
        # Airflow 1
        ("DataProcPySparkOperator", track_dataproc_pyspark_operator),
        # Airflow 2
        ("DataprocSubmitJobOperator", track_dataproc_submit_job_operator),
        ("DataprocSubmitPySparkJobOperator", track_dataproc_pyspark_operator),
        ("SparkSubmitOperator", track_spark_submit_operator),
        ("ECSOperator", track_ecs_operator),
    }
)


def register_airflow_operator_handler(operator, airflow_operator_handler):
    logger.debug(
        "Registering operator handler %s with %s", operator, airflow_operator_handler
    )
    global _EXECUTE_TRACKING
    if isinstance(operator, type):
        operator = operator.__module__ + operator.__qualname__
    _EXECUTE_TRACKING[operator] = airflow_operator_handler


def get_airflow_operator_handlers_config(user_config_airflow_operator_handlers=None):
    if user_config_airflow_operator_handlers:
        target = _EXECUTE_TRACKING.copy()
        target.update(user_config_airflow_operator_handlers)
        return target

    return _EXECUTE_TRACKING


def wrap_operator_with_tracking_info(
    tracking_info: Dict[str, str],
    operator: Any,
    airflow_operator_handlers: Dict[str, str],
) -> Optional[ContextManager]:
    """
    Wrap the operator with relevant tracking method, if found such method.
    """
    for class_name, tracking_wrapper in airflow_operator_handlers.items():
        if tracking_wrapper is None:
            continue
        logger.debug(
            " %s %s %s",
            operator,
            class_name,
            is_instance_by_class_name(operator, class_name),
        )
        if is_instance_by_class_name(operator, class_name):
            if isinstance(tracking_wrapper, str):
                tracking_wrapper = load_python_callable(tracking_wrapper)

            return tracking_wrapper(operator, tracking_info)

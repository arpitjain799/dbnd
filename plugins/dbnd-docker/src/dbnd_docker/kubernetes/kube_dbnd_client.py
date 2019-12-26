import logging
import pprint
import sys
import time
import typing

from datetime import datetime

import six

from airflow.contrib.kubernetes.pod_launcher import PodStatus

from dbnd._core.constants import TaskRunState
from dbnd._core.current import try_get_databand_run
from dbnd._core.errors import DatabandError, DatabandRuntimeError, friendly_error
from dbnd._core.log.logging_utils import override_log_formatting
from dbnd._core.task_run.task_run_error import TaskRunError
from dbnd._vendor.click._unicodefun import click
from dbnd_airflow.airflow_extensions.dal import get_airflow_task_instance_state
from dbnd_docker.kubernetes.kube_resources_checker import DbndKubeResourcesChecker
from dbnd_docker.kubernetes.kubernetes_engine_config import (
    KubernetesEngineConfig,
    readable_pod_request,
)
from kubernetes import client
from kubernetes.client.rest import ApiException


if typing.TYPE_CHECKING:
    from airflow.contrib.kubernetes.pod import Pod
    from dbnd._core.task_run.task_run import TaskRun
    from kubernetes.client import CoreV1Api
logger = logging.getLogger(__name__)


class DbndKubernetesClient(object):
    def __init__(self, kube_client, engine_config):
        # type:(DbndKubernetesClient, CoreV1Api,KubernetesEngineConfig)->None
        super(DbndKubernetesClient, self).__init__()

        self.kube_client = kube_client
        self.engine_config = engine_config

        # will be used to low level pod interactions
        self.running_pods = {}

    def end(self):
        logger.info("Deleting submitted pods: %s" % self.running_pods)
        for pod_id, pod_namespace in six.iteritems(self.running_pods):
            self.delete_pod(pod_id, pod_namespace)

    def run_pod(self, task_run, pod, detach_run=False):
        # type: (TaskRun, Pod, bool) -> DbndPodCtrl
        # we add to running first, so we can prevent racing condition
        self.running_pods[pod.name] = pod.namespace

        ec = self.engine_config

        detach_run = detach_run or ec.detach_run
        if ec.show_pod_log:
            logger.info(
                "%s is True,  will send every docker in blocking mode",
                ec.task_name,
                "show_pod_logs",
            )
            detach_run = False
        if ec.debug:
            logger.info(
                "%s is True,  will send every docker in blocking mode",
                ec.task_name,
                "debug",
            )
            detach_run = False

        req = self.engine_config.build_kube_pod_req(pod)
        readable_req_str = readable_pod_request(req)

        if ec.debug:
            logger.info("Pod Creation Request: \n%s", readable_req_str)
            pod_file = task_run.task_run_attempt_file("pod.yaml")
            pod_file.write(readable_req_str)
            logger.debug("Pod Request has been saved to %s", pod_file)

        dashboard_url = ec.get_dashboard_link(pod)
        pod_log = ec.get_pod_log_link(pod)
        external_link_dict = dict()
        if dashboard_url:
            external_link_dict["k8s_dashboard"] = dashboard_url
        if pod_log:
            external_link_dict["pod_log"] = pod_log
        if external_link_dict:
            task_run.set_external_resource_urls(external_link_dict)
        task_run.set_task_run_state(TaskRunState.QUEUED)
        pod_ctrl = self.get_pod_ctrl(pod.name, pod.namespace)
        try:
            resp = self.kube_client.create_namespaced_pod(
                body=req, namespace=pod.namespace
            )
            logger.debug("Pod Creation Response: %s", resp)
        except ApiException as ex:
            task_run_error = TaskRunError.buid_from_ex(ex, task_run)
            task_run.set_task_run_state(TaskRunState.FAILED, error=task_run_error)
            logger.error(
                "Exception when attempting to create Namespaced Pod using: %s",
                readable_req_str,
            )
            raise
        logging.debug("Kubernetes Job created!")

        # TODO this is pretty dirty.
        #  Better to extract the deploy error checking logic out of the pod launcher and have the watcher
        #   pass an exception through the watcher queue if needed. Current airflow implementation doesn't implement that, so we will stick with the current flow

        if detach_run:
            return pod_ctrl

        pod_ctrl.wait()
        return pod_ctrl

    def get_pod_ctrl(self, name, namespace=None):
        return DbndPodCtrl(
            pod_name=name,
            pod_namespace=namespace or self.engine_config.namespace,
            kube_client=self.kube_client,
            kube_config=self.engine_config,
        )

    def delete_pod(self, name, namespace):
        self.get_pod_ctrl(name=name, namespace=namespace).delete_pod()

    def process_pod_event(self, event):
        pod_data = event["object"]

        if event["type"] == "ERROR":
            return None

        pod_name = pod_data.metadata.name
        phase = pod_data.status.phase
        if phase == "Pending":
            logger.info("Event: %s is Pending", pod_name)
            pod_ctrl = self.get_pod_ctrl(name=pod_name)
            try:
                pod_ctrl.check_deploy_errors(pod_data)
            except Exception as ex:
                self.dbnd_set_task_pending_fail(pod_data, ex)
                return "Failed"
        elif phase == "Failed":
            self.dbnd_set_task_failed(pod_data)

            logger.info("Event: %s Failed", pod_name)
        elif phase == "Succeeded":
            logger.info("Event: %s Succeeded", pod_name)
        elif phase == "Running":
            logger.info("Event: %s is Running", pod_name)
        else:
            logger.info(
                "Event: Invalid state: %s on pod: %s with labels: %s with "
                "resource_version: %s",
                phase,
                pod_name,
                pod_data.metadata.labels,
                pod_data.metadata.resource_version,
            )

        return phase

    def dbnd_set_task_pending_fail(self, pod_data, ex):
        metadata = pod_data.metadata
        logs = None

        task_run = _get_task_run_from_pod_data(pod_data)
        if not task_run:
            return
        from dbnd._core.task_run.task_run_error import TaskRunError

        task_run_error = TaskRunError.buid_from_ex(ex, task_run)

        try:
            pp = pprint.PrettyPrinter(indent=4)
            logs = pp.pformat(pod_data.status)
            logger.info(logs)
        except Exception as ex:
            logger.error("failed to get pod status log for %s: %s", metadata.name, ex)
        logger.info(
            "Pod is Pending with exception, marking it as failed. Pod Status:\n%s", logs
        )
        task_run.set_task_run_state(TaskRunState.FAILED, error=task_run_error)
        task_run.tracker.save_task_run_log(logs)

    def dbnd_set_task_failed(self, pod_data):
        metadata = pod_data.metadata
        logger.debug("getting failure info")
        # noinspection PyBroadException
        pod_ctrl = self.get_pod_ctrl(metadata.name, metadata.namespace)
        logs = []
        try:
            log_printer = lambda x: logs.append(x)
            pod_ctrl.stream_pod_logs(
                print_func=log_printer, tail_lines=100, follow=False
            )
        except Exception as ex:
            logger.error("failed to get log for %s: %s", metadata.name, ex)

        logger.debug("Getting task run")
        task_run = _get_task_run_from_pod_data(pod_data)
        if not task_run:
            logger.info("Can't find a task run for %s", metadata.name)
            return

        from dbnd._core.task_run.task_run_error import TaskRunError

        # work around to build an error object
        try:
            raise DatabandError(
                "Pod %s at %s has failed! (15 lines of log, see more details in UI):\n%s"
                % (metadata.name, metadata.namespace, "\n".join(logs[:15])),
                show_exc_info=False,
                help_msg="Please see full pod log for more details",
            )
        except DatabandError as ex:
            error = TaskRunError.buid_from_ex(ex, task_run)

        task_state = get_airflow_task_instance_state(task_run=task_run)

        logger.debug("task airflow state: %s ", task_state)
        from airflow.utils.state import State

        if task_state == State.FAILED:
            # let just notify the error, so we can show it in summary it
            # we will not send it to databand tracking store
            task_run.set_task_run_state(TaskRunState.FAILED, track=False, error=error)
            logger.info(
                "%s",
                task_run.task.ctrl.banner(
                    "Task %s has failed at pod %s!"
                    % (metadata.name, task_run.task.task_name),
                    color="red",
                    task_run=task_run,
                ),
            )
        else:
            task_run.set_task_run_state(TaskRunState.FAILED, track=True, error=error)
            if logs:
                task_run.tracker.save_task_run_log("\n".join(logs))


class DbndPodCtrl(object):
    def __init__(self, pod_name, pod_namespace, kube_config, kube_client):
        self.kube_config = kube_config
        self.name = pod_name
        self.namespace = pod_namespace
        self.kube_client = kube_client

    def delete_pod(self):
        if not self.kube_config.keep_finished_pods:
            logger.warning(
                "Will not delete pod '%s' due to keep_finished_pods=True.", self.name
            )
            return

        from airflow.utils.state import State

        if (
            self.kube_config.keep_failed_pod
            and self.get_airflow_state() == State.FAILED
        ):
            logger.warning(
                "Keeping failed pod '%s' due to keep_failed_pods=True.", self.name
            )
            return

        logger.info("Deleting pod: %s" % self.name)

        try:
            self.kube_client.delete_namespaced_pod(
                self.name, self.namespace, body=client.V1DeleteOptions()
            )
        except ApiException as e:
            # If the pod is already deleted
            if e.status != 404:
                raise

    def get_pod_status_v1(self):
        from requests import HTTPError

        try:
            return self.kube_client.read_namespaced_pod(self.name, self.namespace)
        except HTTPError as e:
            raise DatabandRuntimeError(
                "There was an error reading pod status for %s at namespace %s via kubernetes API: {}".format(
                    e
                )
            )

    def get_airflow_state(self):
        """Process phase infomration for the JOB"""
        try:
            pod_resp = self.get_pod_status_v1()
            return self._phase_to_airflow_state(pod_resp.status.phase)
        except Exception as e:
            logger.warning("failed to read pod state for %s: %s", self.name, e)
            return None

    def _wait_for_pod_started(self, _logger=logger):
        """
        will try to raise an exception if the pod fails to start (see DbndPodLauncher.check_deploy_errors)
        """
        start_time = datetime.now()
        while True:
            pod_status = self.get_pod_status_v1()
            # PATCH:  validate deploy errors
            self.check_deploy_errors(pod_status)

            pod_phase = pod_status.status.phase
            if pod_phase.lower() != PodStatus.PENDING:
                return

            startup_delta = datetime.now() - start_time
            if startup_delta >= self.kube_config.startup_timeout:
                raise DatabandError("Pod is still not running after %s" % startup_delta)
            time.sleep(1)
            _logger.debug("Pod not yet started: %s", pod_status.status)

    def stream_pod_logs(self, print_func=logger.info, follow=False, tail_lines=10):
        kwargs = {
            "name": self.name,
            "namespace": self.namespace,
            "container": "base",
            "follow": follow,
            "tail_lines": tail_lines,
            "_preload_content": False,
        }

        logs = self.kube_client.read_namespaced_pod_log(**kwargs)
        try:
            if self.kube_config.prefix_remote_log:
                # we want to remove regular header in log, and make it looks like '[pod_name] LOG FROM POD'
                prefix = "[%s]" % self.name
                with override_log_formatting(prefix + "%(message)s"):
                    for line in logs:
                        print_func(line[:-1].decode("utf-8"))
            else:
                for line in logs:
                    print_func(line[:-1].decode("utf-8"))
        except Exception as ex:
            logger.error("Failed to stream logs for %s:  %s", self.name, ex)

    def check_deploy_errors(self, pod_v1_resp):
        pod_status = pod_v1_resp.status
        if pod_status.conditions:
            for condition in pod_status.conditions:
                if (
                    condition.reason == "Unschedulable"
                    and self.kube_config.check_unschedulable_condition
                ):
                    logger.info("pod is pending because %s" % condition.message)
                    if (
                        "Insufficient cpu" in condition.message
                        or "Insufficient memory" in condition.message
                    ):
                        if self.kube_config.check_cluster_resource_capacity:
                            kube_resources_checker = DbndKubeResourcesChecker(
                                kube_client=self.kube_client,
                                kube_config=self.kube_config,
                            )
                            kube_resources_checker.check_if_resource_request_above_max_capacity(
                                condition.message
                            )

                        logger.warning("pod is pending because %s" % condition.message)
                    else:
                        raise friendly_error.executor_k8s.kubernetes_pod_unschedulable(
                            condition.message
                        )

        if pod_status.container_statuses:
            container_waiting_state = pod_status.container_statuses[0].state.waiting
            if pod_status.phase == "Pending" and container_waiting_state:
                if container_waiting_state.reason == "ErrImagePull":
                    logger.info(
                        "Found problematic condition at %s :%s %s",
                        self.name,
                        container_waiting_state.reason,
                        container_waiting_state.message,
                    )
                    raise friendly_error.executor_k8s.kubernetes_image_not_found(
                        pod_status.container_statuses[0].image,
                        container_waiting_state.message,
                    )

                if container_waiting_state.reason == "CreateContainerConfigError":
                    raise friendly_error.executor_k8s.kubernetes_pod_config_error(
                        container_waiting_state.message
                    )

    def _phase_to_airflow_state(self, pod_phase):
        """Process phase infomration for the JOB"""
        phase = pod_phase.lower()
        from airflow.utils.state import State

        if phase == PodStatus.PENDING:
            return State.QUEUED
        elif phase == PodStatus.FAILED:
            logger.info("Event with pod %s Failed", self.name)
            return State.FAILED
        elif phase == PodStatus.SUCCEEDED:
            logger.info("Event with pod %s Succeeded", self.name)
            return State.SUCCESS
        elif phase == PodStatus.RUNNING:
            return State.RUNNING
        else:
            logger.info("Event: Invalid state %s on job %s", phase, self.name)
            return State.FAILED

    def wait(self):
        """
        Waits for pod completion
        :return:
        """
        self._wait_for_pod_started()
        logger.info("Pod '%s' is running, reading logs..", self.name)
        self.stream_pod_logs(follow=True)
        logger.info("Successfully read %s pod logs", self.name)
        final_state = self.get_airflow_state()
        from airflow.utils.state import State

        if final_state != State.SUCCESS:
            raise DatabandRuntimeError(
                "Pod returned a failure: {state}".format(state=final_state)
            )
        return self


def _get_task_run_from_pod_data(pod_data):
    labels = pod_data.metadata.labels
    if "task_id" not in labels:
        return None
    task_id = labels["task_id"]

    dr = try_get_databand_run()
    if not dr:
        return None

    return dr.get_task_run_by_af_id(task_id)

import random
import string

from functools import wraps

import pytest

from mock import MagicMock, patch

from airflow_monitor.config import AirflowMonitorConfig
from airflow_monitor.multiserver.monitor_component_manager import (
    AirflowMonitorComponentManager,
)
from airflow_monitor.multiserver.multiserver import AirflowMultiServerMonitor
from airflow_monitor.shared.runners import RUNNER_FACTORY
from airflow_monitor.syncer.runtime_syncer import AirflowRuntimeSyncer
from airflow_monitor.tracking_service import get_servers_configuration_service
from dbnd._core.errors import DatabandConfigError

from .conftest import WebAppTest


@pytest.fixture
def mock_sync_once():
    with patch.object(
        AirflowRuntimeSyncer,
        "_sync_once",
        new=mock_decorator(AirflowRuntimeSyncer._sync_once),
    ) as patched_sync_once:
        yield patched_sync_once.mock


def mock_decorator(method_to_decorate):
    mock = MagicMock()

    @wraps(method_to_decorate)
    def wrapper(*args, **kwargs):
        res = method_to_decorate(*args, **kwargs)
        mock(*args, **kwargs)
        return res

    wrapper.mock = mock
    return wrapper


class TestSyncerWorks(WebAppTest):
    def set_is_monitor_enabled(self, uid, is_sync_enabled):
        self.client.post(
            self._url("AirflowServersApi.set_is_enabled"),
            json={"tracking_source_uid": uid, "is_enabled": is_sync_enabled},
        )

    def set_monitor_archived(self, uid):
        self.client.post(self._url("AirflowServersApi.archive"), json=uid)

    def set_monitor_unarchived(self, uid):
        self.client.post(self._url("AirflowServersApi.unarchive"), json=uid)

    def get_server_info_by_tracking_source_uid(self, tracking_source_uid):
        servers = self.client.get(self._url("AirflowServersApi.get_airflow_monitors"))
        for server in servers.json["data"]:
            if server["tracking_source_uid"] == tracking_source_uid:
                return server

    @pytest.fixture
    def syncer(self, _web_app_ctrl_with_login):
        random_name = "".join(random.choice(string.ascii_letters) for _ in range(10))
        created_syncer = self.client.post(
            self._url("AirflowServersApi.add"),
            json={
                "base_url": f"https://{random_name}.local",
                "name": random_name,
                "fetcher": "web",
                "external_url": "",
                "composer_client_id": "",
                "api_mode": "rbac",
                "airflow_environment": "on_prem",
                "dag_ids": "",
                "monitor_config": {"include_sources": False},
            },
        )

        syncer_dict = created_syncer.json

        return {
            "tracking_source_uid": syncer_dict["tracking_source_uid"],
            "name": random_name,
            **syncer_dict["server_info_dict"],
        }

    @pytest.fixture
    def multi_server(self, mock_data_fetcher, syncer):
        with patch(
            "airflow_monitor.multiserver.monitor_component_manager.get_data_fetcher",
            return_value=mock_data_fetcher,
        ), patch(
            "airflow_monitor.common.base_component.get_data_fetcher",
            return_value=mock_data_fetcher,
        ), self.patch_api_client():
            syncer_name = syncer["name"]
            monitor_config = AirflowMonitorConfig(syncer_name=syncer_name)
            yield AirflowMultiServerMonitor(
                runner=RUNNER_FACTORY[monitor_config.runner_type],
                monitor_component_manager=AirflowMonitorComponentManager,
                servers_configuration_service=get_servers_configuration_service(),
                monitor_config=monitor_config,
            )

    def test_01_server_sync_enable_disable(self, multi_server, syncer, mock_sync_once):
        tracking_source_uid = syncer["tracking_source_uid"]
        server_info = self.get_server_info_by_tracking_source_uid(tracking_source_uid)
        assert server_info["last_sync_time"] is None

        multi_server.run_once()
        assert mock_sync_once.call_count == 1

        server_info = self.get_server_info_by_tracking_source_uid(tracking_source_uid)
        assert server_info["last_sync_time"] is not None
        last_sync_time = server_info["last_sync_time"]

        self.set_is_monitor_enabled(tracking_source_uid, False)
        multi_server.run_once()
        assert mock_sync_once.call_count == 1

        server_info = self.get_server_info_by_tracking_source_uid(tracking_source_uid)
        assert server_info["last_sync_time"] == last_sync_time

        self.set_is_monitor_enabled(tracking_source_uid, True)
        multi_server.run_once()
        assert mock_sync_once.call_count == 2

        server_info = self.get_server_info_by_tracking_source_uid(tracking_source_uid)
        assert server_info["last_sync_time"] > last_sync_time

    def test_02_server_archive_unarchive(self, multi_server, syncer, mock_sync_once):
        tracking_source_uid = syncer["tracking_source_uid"]
        multi_server.run_once()
        assert mock_sync_once.call_count == 1

        self.set_monitor_archived(tracking_source_uid)

        with pytest.raises(DatabandConfigError):
            multi_server.run_once()

        assert mock_sync_once.call_count == 1

        self.set_monitor_unarchived(tracking_source_uid)

        # We need to clean all inactive components so that in the next sync_once() we will create them from scratch.
        # This is crucial as otherwise we will have a last_heartbeat value in SequentialRunner, which will result in
        # a quick return from the heartbeat function without executing sync_once.
        # This is because the sync_once above raises exception instead of cleaning and then we reuse the same object.
        multi_server._ensure_monitored_servers([])

        multi_server.run_once()
        assert mock_sync_once.call_count == 2

    def test_03_source_instance_uid(
        self, multi_server, syncer, mock_sync_once, mock_data_fetcher
    ):
        tracking_source_uid = syncer["tracking_source_uid"]
        mock_data_fetcher.airflow_version = "1.10.10"
        mock_data_fetcher.plugin_version = "0.40.1 v2"
        mock_data_fetcher.airflow_instance_uid = "34db92af-a525-522e-8f27-941cd4746d7b"

        server_info = self.get_server_info_by_tracking_source_uid(tracking_source_uid)
        assert (
            server_info["airflow_version"],
            server_info["airflow_export_version"],
            server_info["source_instance_uid"],
        ) == (None, None, None)

        multi_server.run_once()

        server_info = self.get_server_info_by_tracking_source_uid(tracking_source_uid)
        assert (
            server_info["airflow_version"],
            server_info["airflow_export_version"],
            server_info["source_instance_uid"],
        ) == ("1.10.10", "0.40.1 v2", "34db92af-a525-522e-8f27-941cd4746d7b")

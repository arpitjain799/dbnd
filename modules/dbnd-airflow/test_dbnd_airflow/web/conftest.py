import logging

import pytest

from dbnd._core.plugin.dbnd_plugins import is_web_enabled
from dbnd_airflow.airflow_override.dbnd_aiflow_webserver import (
    use_databand_airflow_dagbag,
)
from dbnd_airflow.web.airflow_app import create_app
from test_dbnd_airflow.utils import WebAppCtrl


logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def web_app():

    app, appbuilder = create_app(testing=True)
    app.config["WTF_CSRF_ENABLED"] = False
    app.web_appbuilder = appbuilder

    use_databand_airflow_dagbag()
    return app


@pytest.fixture(scope="session")
def web_client(web_app):
    with web_app.test_client() as c:
        yield c
        logger.info("web client is closed")


@pytest.fixture
def web_app_ctrl(web_app, web_client):
    return WebAppCtrl(app=web_app, appbuilder=web_app.web_appbuilder, client=web_client)


@pytest.fixture(scope="class", autouse=True)
def unpatched_airflow_security_manager():
    if not is_web_enabled():
        yield
        return

    from dbnd_web.models.security import patch_manager, unpatch_manager

    try:
        unpatch_manager()
        yield
    finally:
        patch_manager()

import attr


@attr.s
class AirflowServerConfig(object):
    tracking_source_uid = attr.ib()  # type: UUID
    state_sync_enabled = attr.ib(default=False)  # type: bool
    xcom_sync_enabled = attr.ib(default=False)  # type: bool
    dag_sync_enabled = attr.ib(default=False)  # type: bool
    fixer_enabled = attr.ib(default=False)  # type: bool

    is_sync_enabled = attr.ib(default=True)  # type: bool
    base_url = attr.ib(default=None)  # type: str
    api_mode = attr.ib(default=None)  # type: str
    fetcher = attr.ib(default="web")  # type: str

    # for web data fetcher
    rbac_username = attr.ib(default=None)  # type: str
    rbac_password = attr.ib(default=None)  # type: str

    # for composer data fetcher
    composer_client_id = attr.ib(default=None)  # type: str

    # for db data fetcher
    local_dag_folder = attr.ib(default=None)  # type: str
    sql_alchemy_conn = attr.ib(default=None)  # type: str

    # for file data fetcher
    json_file_path = attr.ib(default=None)  # type: str

    @classmethod
    def create(cls, airflow_config, server_config):
        monitor_config = server_config.get("monitor_config") or {}
        kwargs = {k: v for k, v in monitor_config.items() if k in attr.fields_dict(cls)}

        conf = cls(
            tracking_source_uid=server_config["tracking_source_uid"],
            is_sync_enabled=server_config["is_sync_enabled"],
            base_url=server_config["base_url"],
            api_mode=server_config["api_mode"],
            fetcher=server_config["fetcher"],
            composer_client_id=server_config["composer_client_id"],
            sql_alchemy_conn=airflow_config.sql_alchemy_conn,  # TODO: currently support only one server!
            json_file_path=airflow_config.json_file_path,  # TODO: currently support only one server!
            rbac_username=airflow_config.rbac_username,  # TODO: currently support only one server!
            rbac_password=airflow_config.rbac_password,  # TODO: currently support only one server!
            **kwargs,
        )
        return conf


@attr.s
class MonitorConfig(AirflowServerConfig):
    init_dag_run_bulk_size = attr.ib(default=10)  # type: int

    max_execution_date_window = attr.ib(default=14)  # type: int
    interval = attr.ib(default=10)  # type: int


@attr.s
class MultiServerMonitorConfig:
    interval = attr.ib(default=0)
    runner_type = attr.ib(default="seq")  # seq/mp
    number_of_iterations = attr.ib(default=None)  # type: Optional[int]
    tracking_source_uids = attr.ib(
        default=None, converter=lambda v: list(v) if v else v,
    )  # type: Optional[List[UUID]]


@attr.s
class TrackingServiceConfig:
    url = attr.ib()
    access_token = attr.ib(default=None)
    user = attr.ib(default=None)
    password = attr.ib(default=None)

from typing import Any


mandatory_keys: dict[str, str] = {"initial_mess": "",
                                  "ct_yaml": ""
                                  }

default_settings: dict[str, Any] = {
    "project_name": "gameProject",
    "rc_software": "mess",
    "rc_temp": [],
    "rc_pres": [],
    "ct_names": {},
    "cpu_kin": 4,
    "mem_kin": 10000,
    "cpu_sim": 1,
    "mem_sim": 500,
    "max_mem": 1000000,
    "max_cpu": 1000,
    "max_jobs": 2000,
    "remote_host": "127.0.0.1"
}

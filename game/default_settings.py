from typing import Any


mandatory_keys: dict[str, str] = {"initial_mess": "",
                                  "ct_yaml": ""
                                  }

default_settings: dict[str, Any] = {
    "rc_software": "mess",
    "rc_nproc": 1,
    "rc_temp": [],
    "rc_pres": [],
    "ct_names": {}
}

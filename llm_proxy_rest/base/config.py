import json
from typing import Dict


class ApiModelConfig:
    def __init__(self, models_config_path: str):
        self.models_config_path = models_config_path

        self.active_models = self._read_active_models()
        self.models_configs = self._active_models_configuration()

    def _read_active_models(
        self,
    ) -> Dict[str, str]:
        models_config = json.load(open(self.models_config_path, "rt"))
        if len(models_config):
            exists_model = False
            for model_type, model_list in models_config.items():
                if len(model_list):
                    exists_model = True
                    break
            if not exists_model:
                return {}
        return models_config["active_models"]

    def _active_models_configuration(self) -> Dict:
        models_configuration = {}
        models_json = json.load(open(self.models_config_path, "rt"))
        for m_type, models_list in self.active_models.items():
            for m_name in models_list:
                models_configuration[m_name] = models_json[m_type][m_name]
        return models_configuration

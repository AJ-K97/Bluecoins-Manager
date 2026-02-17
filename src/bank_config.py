import json
import os


DEFAULT_BANK_CONFIG_PATH = "data/banks_config.json"


def load_banks_payload(config_path=DEFAULT_BANK_CONFIG_PATH):
    if not os.path.exists(config_path):
        return {"banks": {}}
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "banks" not in data or not isinstance(data["banks"], dict):
        data["banks"] = {}
    return data


def list_bank_names(config_path=DEFAULT_BANK_CONFIG_PATH):
    payload = load_banks_payload(config_path)
    return sorted(payload["banks"].keys())


def save_banks_payload(payload, config_path=DEFAULT_BANK_CONFIG_PATH):
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=True)
        f.write("\n")


def upsert_bank_format(bank_name, bank_cfg, config_path=DEFAULT_BANK_CONFIG_PATH):
    payload = load_banks_payload(config_path)
    payload["banks"][bank_name] = bank_cfg
    save_banks_payload(payload, config_path)

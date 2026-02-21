import requests
from flask import Blueprint, jsonify, current_app
from app.utils_homeassistant import HomeAssistantConfig
from app.labeldesigner.printer import reset_printer_cache

bp = Blueprint("printer_power", __name__)


@bp.route("/api/printer_power/status", methods=["GET"])
def printer_power_status():
    cfg = HomeAssistantConfig()
    if not cfg.is_configured():
        return jsonify({"error": "Home Assistant not configured"}), 400
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    url = f"{cfg.api_url}/states/{cfg.entity_id}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        state = resp.json().get("state")
        return jsonify({"state": state})
    except Exception as e:
        current_app.logger.error(f"Failed to get printer power status: {e}")
        return jsonify({"error": "Failed to get printer power status"}), 500


@bp.route("/api/printer_power/toggle", methods=["POST"])
def printer_power_toggle():
    cfg = HomeAssistantConfig()
    if not cfg.is_configured():
        return jsonify({"error": "Home Assistant not configured"}), 400
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    url = f"{cfg.api_url}/services/switch/toggle"
    data = {"entity_id": cfg.entity_id}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=5)
        resp.raise_for_status()
        reset_printer_cache()
        return jsonify({"result": "success"})
    except Exception as e:
        current_app.logger.error(f"Failed to toggle printer power: {e}")
        return jsonify({"error": "Failed to toggle printer power"}), 500

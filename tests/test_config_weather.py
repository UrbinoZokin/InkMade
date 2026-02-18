from pathlib import Path

from inkycal.config import load_config


def test_weather_config_defaults_to_goodyear(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("timezone: 'America/Phoenix'\n", encoding="utf-8")

    cfg = load_config(str(cfg_path))

    assert cfg.weather.latitude == 33.4353
    assert cfg.weather.longitude == -112.3582


def test_weather_config_uses_custom_coordinates(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        timezone: 'America/Phoenix'
        weather:
          latitude: 47.6062
          longitude: -122.3321
        """,
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_path))

    assert cfg.weather.latitude == 47.6062
    assert cfg.weather.longitude == -122.3321

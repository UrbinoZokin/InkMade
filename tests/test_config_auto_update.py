from inkycal.config import load_config


def test_auto_update_defaults_to_enabled_on_main(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("timezone: 'America/Phoenix'\n", encoding="utf-8")

    cfg = load_config(str(cfg_path))

    assert cfg.auto_update.enabled is True
    assert cfg.auto_update.branch == "main"
    assert cfg.auto_update.apply_window == "sleep"


def test_auto_update_can_be_disabled_and_retargeted(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        timezone: 'America/Phoenix'
        auto_update:
          enabled: false
          branch: "stable"
          apply_window: "Anytime"
        """,
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_path))

    assert cfg.auto_update.enabled is False
    assert cfg.auto_update.branch == "stable"
    # normalized to lower case for the shell/render to compare against
    assert cfg.auto_update.apply_window == "anytime"

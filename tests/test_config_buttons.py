from inkycal.config import load_config


def test_buttons_default_pins(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("timezone: 'America/Phoenix'\n", encoding="utf-8")

    cfg = load_config(str(cfg_path))

    assert cfg.buttons.enabled is True
    # 13.3" Inky Impression defaults: A/B/D match all sizes, C is GPIO25
    # (not the GPIO16 used on the smaller 4"/5.7"/7.3" boards).
    assert cfg.buttons.pin_view == 5
    assert cfg.buttons.pin_refresh == 6
    assert cfg.buttons.pin_unused == 25
    assert cfg.buttons.pin_update == 24
    assert cfg.buttons.bounce_time_ms == 300


def test_buttons_can_be_overridden_and_disabled(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        timezone: 'America/Phoenix'
        buttons:
          enabled: false
          pin_view: 17
          pin_refresh: 27
          pin_unused: 22
          pin_update: 23
          bounce_time_ms: 150
        """,
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_path))

    assert cfg.buttons.enabled is False
    assert cfg.buttons.pin_view == 17
    assert cfg.buttons.pin_refresh == 27
    assert cfg.buttons.pin_unused == 22
    assert cfg.buttons.pin_update == 23
    assert cfg.buttons.bounce_time_ms == 150

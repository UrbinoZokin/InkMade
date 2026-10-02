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
    assert cfg.buttons.pin_setup == 25
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
          pin_setup: 22
          pin_update: 23
          bounce_time_ms: 150
        """,
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_path))

    assert cfg.buttons.enabled is False
    assert cfg.buttons.pin_view == 17
    assert cfg.buttons.pin_refresh == 27
    assert cfg.buttons.pin_setup == 22
    assert cfg.buttons.pin_update == 23
    assert cfg.buttons.bounce_time_ms == 150


def test_button_c_keeps_the_pin_a_config_written_before_setup_mode_gave_it(tmp_path):
    """config.yaml is the device's own file -- updates never touch it -- so
    one written when button C had no function still names it `pin_unused`.
    A smaller Impression sets it to 16; losing that would bind setup mode to
    the 13.3" board's pin instead."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        timezone: 'America/Phoenix'
        buttons:
          pin_unused: 16
        """,
        encoding="utf-8",
    )

    assert load_config(str(cfg_path)).buttons.pin_setup == 16


def test_button_c_prefers_the_new_name_when_both_are_set(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        timezone: 'America/Phoenix'
        buttons:
          pin_unused: 16
          pin_setup: 22
        """,
        encoding="utf-8",
    )

    assert load_config(str(cfg_path)).buttons.pin_setup == 22


def test_buttons_echo_to_terminals_defaults_on_and_can_be_disabled(tmp_path):
    default_path = tmp_path / "default.yaml"
    default_path.write_text("timezone: 'America/Phoenix'\n", encoding="utf-8")

    assert load_config(str(default_path)).buttons.echo_to_terminals is True

    off_path = tmp_path / "off.yaml"
    off_path.write_text(
        """
        timezone: 'America/Phoenix'
        buttons:
          echo_to_terminals: false
        """,
        encoding="utf-8",
    )

    assert load_config(str(off_path)).buttons.echo_to_terminals is False


def test_buttons_press_feedback_defaults_to_banner_and_is_normalised(tmp_path):
    default_path = tmp_path / "default.yaml"
    default_path.write_text("timezone: 'America/Phoenix'\n", encoding="utf-8")

    assert load_config(str(default_path)).buttons.press_feedback == "banner"

    wipe_path = tmp_path / "wipe.yaml"
    wipe_path.write_text(
        """
        timezone: 'America/Phoenix'
        buttons:
          press_feedback: "  Wipe  "
        """,
        encoding="utf-8",
    )

    assert load_config(str(wipe_path)).buttons.press_feedback == "wipe"

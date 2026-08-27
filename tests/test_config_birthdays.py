from inkycal.config import load_config


def test_contact_birthdays_default_to_enabled(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("timezone: 'America/Phoenix'\n", encoding="utf-8")

    cfg = load_config(str(cfg_path))

    assert cfg.google.birthdays_enabled is True


def test_contact_birthdays_can_be_disabled(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
        timezone: 'America/Phoenix'
        calendars:
          google:
            enabled: true
            calendar_ids:
              - "primary"
            birthdays_enabled: false
        """,
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_path))

    assert cfg.google.birthdays_enabled is False
    assert cfg.google.calendar_ids == ["primary"]

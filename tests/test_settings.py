"""Tests para la persistencia de preferencias (settings.py)."""

from settings import AppSettings, SettingsStore


def test_defaults_when_no_file(tmp_path):
    """Sin fichero previo, se usan los valores por defecto.

    `QSettings` puede devolver valores ya guardados de una ejecución
    anterior, así que el test fuerza el backend JSON para ser determinista.
    """
    store = SettingsStore(fallback_path=tmp_path / "settings.json")
    store._settings = None
    settings = store.load()
    assert settings.subtitles is True
    assert settings.whisper_model == "base"


def test_json_fallback_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(fallback_path=path)
    # Fuerza el fallback JSON (sin QSettings disponible).
    store._settings = None

    original = AppSettings(
        subtitles=False,
        whisper_model="turbo",
        language="es",
        branding=True,
        logo_path="/tmp/logo.png",
        cleanup_intermediates=True,
        word_highlight=False,
        loudnorm=False,
    )
    assert store.save(original) is True

    reloaded = SettingsStore(fallback_path=path)
    reloaded._settings = None
    loaded = reloaded.load()

    assert loaded.subtitles is False
    assert loaded.whisper_model == "turbo"
    assert loaded.language == "es"
    assert loaded.branding is True
    assert loaded.logo_path == "/tmp/logo.png"
    assert loaded.cleanup_intermediates is True
    assert loaded.word_highlight is False
    assert loaded.loudnorm is False


def test_from_dict_ignores_unknown_keys():
    settings = AppSettings.from_dict({"whisper_model": "small", "campo_inventado": 1})
    assert settings.whisper_model == "small"
    assert not hasattr(settings, "campo_inventado")


def test_load_handles_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("no es json", encoding="utf-8")
    store = SettingsStore(fallback_path=path)
    store._settings = None
    assert store.load().whisper_model == "base"

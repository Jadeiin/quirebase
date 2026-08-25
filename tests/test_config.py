from quirebase.core.config import Settings


def test_inquiro_environment_configures_embedded_provider_runtime(monkeypatch):
    monkeypatch.setenv("INQUIRO_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("INQUIRO_MAX_RESPONSE_BYTES", "4096")
    monkeypatch.setenv("INQUIRO_CONTACT_EMAIL", "operator@example.org")
    monkeypatch.setenv("INQUIRO_NCBI_API_KEY", "ncbi-key")
    monkeypatch.setenv("INQUIRO_OPENALEX_API_KEY", "openalex-key")
    monkeypatch.setenv("INQUIRO_NASA_ADS_TOKEN", "ads-token")
    monkeypatch.setenv("INQUIRO_IEEE_API_KEY", "ieee-key")

    settings = Settings(_env_file=None)

    assert settings.metadata_timeout_seconds == 12
    assert settings.metadata_max_response_bytes == 4096
    assert settings.metadata_contact_email == "operator@example.org"
    assert settings.ncbi_api_key == "ncbi-key"
    assert settings.openalex_api_key == "openalex-key"
    assert settings.nasa_ads_token == "ads-token"
    assert settings.ieee_api_key == "ieee-key"

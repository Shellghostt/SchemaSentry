from schemasentry import __version__


def test_version_is_semver_like() -> None:
    assert __version__ == "0.0.0"

from importlib.metadata import version as package_version

from schemasentry import __version__


def test_version_is_semver_like() -> None:
    assert __version__ == "0.1.0"


def test_package_metadata_matches_the_module() -> None:
    assert package_version("schemasentry") == __version__

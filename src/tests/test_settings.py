from app.config import Settings


def test_filesystem_roots_prefers_fs_root_over_default_roots() -> None:
    settings = Settings(_env_file=None, FS_ROOT="/tmp/workspace")

    assert settings.filesystem_roots() == ["/tmp/workspace"]

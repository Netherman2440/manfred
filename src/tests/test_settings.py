from app.config import Settings


def test_mount_names_returns_list_from_fs_mounts() -> None:
    settings = Settings(_env_file=None, FS_MOUNTS="agents,skills,workflows,shared")

    assert settings.mount_names() == ["agents", "skills", "workflows", "shared"]


def test_mount_names_strips_slashes_and_spaces() -> None:
    settings = Settings(_env_file=None, FS_MOUNTS=" agents/, /shared ")

    assert settings.mount_names() == ["agents", "shared"]


def test_mount_names_ignores_empty_segments() -> None:
    settings = Settings(_env_file=None, FS_MOUNTS="agents,,shared,")

    assert settings.mount_names() == ["agents", "shared"]

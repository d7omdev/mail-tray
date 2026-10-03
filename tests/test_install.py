"""Install a wheel with a sandboxed user base; never touch system Python or files."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not Path('/usr/bin/python3').exists(), reason='Linux system Python required')
def test_no_venv_installer_creates_cli_icon_config_and_launcher(tmp_path):
    keyring = pytest.importorskip('keyring')
    project = tmp_path / 'project'
    project.mkdir()
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / 'mailtray', project / 'mailtray', ignore=shutil.ignore_patterns('__pycache__'))
    for filename in ('pyproject.toml', 'install.sh'):
        shutil.copy2(root / filename, project / filename)
    bin_dir = tmp_path / 'stubs'
    bin_dir.mkdir()
    sudo = bin_dir / 'sudo'
    sudo.write_text('#!/bin/sh\nexit 0\n')
    sudo.chmod(0o755)
    data = tmp_path / 'data'
    config = tmp_path / 'config'
    user_base = tmp_path / 'user-base'
    desktop = data / 'applications' / 'mail-tray.desktop'
    desktop.parent.mkdir(parents=True)
    previous = '[Desktop Entry]\nName=Mail Tray\nExec="/old/.venv-gtk/bin/mail-tray"\n'
    desktop.write_text(previous)
    env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}',
           'PYTHONUSERBASE': str(user_base), 'PYTHONPATH': str(Path(keyring.__file__).parents[1]),
           'XDG_CONFIG_HOME': str(config), 'XDG_DATA_HOME': str(data), 'MAIL_TRAY_SKIP_SETUP': '1'}
    result = subprocess.run(['bash', str(project / 'install.sh')], cwd=project, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (project / '.venv').exists() and not (project / '.venv-gtk').exists()
    assert (user_base / 'bin' / 'mail-tray').exists()
    assert (data / 'icons/hicolor/128x128/apps/mail-tray.png').is_file()
    assert (desktop.with_suffix('.desktop.previous')).read_text() == previous
    assert f'Exec="{user_base}/bin/mail-tray"' in desktop.read_text()
    assert 'Icon=mail-tray' in desktop.read_text()
    assert (config / 'mail-tray' / 'settings.ini').is_file()
    cli = subprocess.run([str(user_base / 'bin/mail-tray'), 'config'], cwd=tmp_path,
                         env=env, capture_output=True, text=True, timeout=10)
    assert cli.returncode == 0, cli.stderr
    assert cli.stdout.strip() == str(config / 'mail-tray/settings.ini')
    again = subprocess.run(['bash', str(project / 'install.sh')], cwd=project, env=env,
                           capture_output=True, text=True, timeout=120)
    assert again.returncode == 0, again.stdout + again.stderr
    assert 'launcher is already current' in again.stdout
    assert (desktop.with_suffix('.desktop.previous')).read_text() == previous

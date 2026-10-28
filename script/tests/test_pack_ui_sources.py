"""The script tmsetup runs on the controller to pack tm-control's UI sources (roles/tmsetup/files/pack-ui-sources.sh).

It packs what git knows about under tm-control/ui (tracked, or untracked and not ignored), as ui/... members, and the
whole directory when git can't say. node_modules and dist never go in.
"""

import os
import shutil
import subprocess
import tarfile

import pytest
from tmsetup_render import ROLE

SCRIPT = ROLE / "files" / "pack-ui-sources.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def write(path, text="x\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def checkout(tmp_path):
    """A repo whose tm-control/ui has tracked, untracked, ignored, and build-output files."""
    repo = tmp_path / "repo"
    ui = repo / "tm-control" / "ui"
    write(repo / ".gitignore", "tm-control/ui/node_modules/\ntm-control/ui/dist/\n*.local\n")
    for name in ("package.json", "src/main.ts", "src/gone.ts"):
        write(ui / name)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    (ui / "src" / "gone.ts").unlink()  # deleted in the working tree, not yet in git
    write(ui / "src" / "new.ts")  # untracked, not ignored: a developer's work in progress goes in
    write(ui / "notes.local")  # ignored
    write(ui / "node_modules" / "vue" / "index.js")
    write(ui / "dist" / "index.html")
    return repo / "tm-control"


def pack(tm_control, archive, env=None):
    result = subprocess.run(["bash", str(SCRIPT), str(tm_control), str(archive)],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    with tarfile.open(archive) as tar:
        return sorted(member.name for member in tar.getmembers() if member.isfile()), result.stdout


def test_packs_the_files_git_lists(checkout, tmp_path):
    names, output = pack(checkout, tmp_path / "ui.tar.gz")
    assert names == ["ui/package.json", "ui/src/main.ts", "ui/src/new.ts"]
    assert "git" in output


def test_packs_the_directory_without_node_modules_or_dist_when_there_is_no_git_checkout(checkout, tmp_path):
    shutil.rmtree(checkout.parent / ".git")
    names, output = pack(checkout, tmp_path / "ui.tar.gz")
    assert names == ["ui/notes.local", "ui/package.json", "ui/src/main.ts", "ui/src/new.ts"]
    assert "no git" in output


def test_packs_the_directory_when_git_is_not_installed(checkout, tmp_path):
    bin_dir = tmp_path / "bin"  # a PATH with bash and tar but no git
    bin_dir.mkdir()
    for tool in ("bash", "tar", "gzip"):
        os.symlink(shutil.which(tool), bin_dir / tool)
    names, _ = pack(checkout, tmp_path / "ui.tar.gz", env={"PATH": str(bin_dir)})
    assert "ui/node_modules/vue/index.js" not in names and "ui/dist/index.html" not in names
    assert "ui/package.json" in names


def test_never_packs_node_modules_or_dist_even_if_git_tracks_them(checkout, tmp_path):
    repo = checkout.parent
    subprocess.run(["git", "-C", str(repo), "add", "-f", "tm-control/ui/node_modules", "tm-control/ui/dist"], check=True)
    names, _ = pack(checkout, tmp_path / "ui.tar.gz")
    assert not [name for name in names if name.startswith(("ui/node_modules", "ui/dist"))]

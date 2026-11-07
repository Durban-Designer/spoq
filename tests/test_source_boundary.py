"""Guard the deliberate source boundary against accidental bulk-copy additions."""
from pathlib import Path
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'code/mcp/spoq-server'


def test_no_private_backend_or_bulk_import_shipped():
    source = PACKAGE / 'src/spoq_server'
    assert not (source / 'stores/api.py').exists()
    assert not (source / 'import_cli.py').exists()
    assert not (PACKAGE / 'tests/fixtures/api_stubs').exists()
    for path in source.rglob('*.py'):
        text = path.read_text()
        assert 'stores.api' not in text, path
        assert 'import_cli' not in text, path


def test_no_local_state_or_deployment_inputs_in_source():
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    for name in ['.aws', '.spoq', '.env', '.pypirc', 'infrastructure', 'spoq', 'session-transcripts']:
        assert not any(path == name or path.startswith(name + '/') for path in tracked), name
    assert not any(path.startswith('code/spoq-website/') for path in tracked)
    for path in (PACKAGE / 'src').rglob('*'):
        assert path.suffix not in {'.db', '.sqlite', '.pem', '.key'}, path
        assert not path.is_symlink(), path


def test_paper_build_is_self_contained():
    paper = ROOT / 'documents/latex/projects/spoq-paper'
    makefile = (paper / 'Makefile').read_text()
    assert 'include ../../' not in makefile
    assert 'spoq-website' not in makefile
    assert (paper / 'src/main.tex').exists()
    assert (paper / 'src/references.bib').exists()


def test_built_distributions_exclude_removed_modules():
    artifacts = list((PACKAGE / 'dist').glob('*'))
    if not artifacts:
        return  # A source checkout need not contain generated artifacts.
    for artifact in artifacts:
        if artifact.suffix == '.whl':
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
        elif artifact.name.endswith('.tar.gz'):
            with tarfile.open(artifact) as archive:
                names = archive.getnames()
        else:
            continue
        assert not any(name.endswith(('/stores/api.py', '/import_cli.py')) for name in names)

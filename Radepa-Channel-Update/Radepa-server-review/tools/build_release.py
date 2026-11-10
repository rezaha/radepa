"""Build an allowlisted source bundle, excluding settings, databases and caches."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.py', '.sql', '.md', '.txt', '.json', '.sh'}
FOLDERS = ('app', 'tests', 'tools', 'docs', 'release')


def payload(root=ROOT):
    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    files=[]
    for name in tracked:
        if not name: continue
        path=root/name
        relative=Path(name)
        allowed=(relative.parts[0] in FOLDERS and path.suffix in EXTENSIONS) or name in ('requirements.txt', 'requirements-sherlock.txt') or (len(relative.parts)==1 and path.suffix=='.md')
        if not allowed: continue
        if path.is_symlink() or path.resolve()!=path.absolute(): raise ValueError('Bundle symlinks are forbidden')
        if path.is_file():files.append(path)
    return sorted(set(files))


def build(output, root=ROOT):
    if subprocess.check_output(['git','status','--porcelain','--','.'],cwd=root).strip():
        raise ValueError('Commit source changes before building a release')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    files = payload(root)
    manifest = {'format': 1, 'source_commit': revision, 'files': {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError('Build artifacts must be outside the source directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'radepa-release/' + path.relative_to(root).as_posix())
        archive.writestr('radepa-release/release-manifest.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Archive integrity failure')
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(f'{checksum}  {output.name}\n')
    return checksum


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output))

#!/usr/bin/env python3
"""Check the public source; optionally build a release from a full Git commit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = frozenset({
    'SKILL.md', 'agents/openai.yaml', 'assets/icon.svg',
    'references/questions.md', 'references/closure-checks-zh.md',
    'references/task-status.md',
    'scripts/task_report.py',
    'LICENSE', 'NOTICE.md',
})
SOURCE = RUNTIME | frozenset({
    '.gitignore', 'AGENTS.md', 'README.md', 'CONTRIBUTING.md', 'VERSION',
    'CHANGELOG.md', 'scripts/check.py', 'tests/test_check.py', 'evals/cases.md',
    'tests/test_task_report.py',
})
IGNORED = {'.git', '__pycache__', 'dist', '.DS_Store'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def validate(root):
    files = set()
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        require(not path.is_symlink(), f'symlink is not allowed: {relative}')
        if path.is_file():
            files.add(relative.as_posix())
    require(files == SOURCE, f'public file list mismatch: missing={sorted(SOURCE-files)}, extra={sorted(files-SOURCE)}')
    skill = (root / 'SKILL.md').read_text(encoding='utf-8')
    require(skill.startswith('---\n') and '\n---\n' in skill[4:], 'missing skill frontmatter')
    meta = skill.split('---', 2)[1]
    require(re.search(r'^name: dot-workflow$', meta, re.M), 'wrong skill identity')
    fields = [line.split(':', 1)[0] for line in meta.strip().splitlines()]
    require(sorted(fields) == ['description', 'name'], 'skill frontmatter must contain only name and description')
    version = (root/'VERSION').read_text().strip()
    require(re.fullmatch(r'(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)', version) is not None, 'missing stable semantic version in VERSION')
    require(f'## [{version}]' in (root / 'CHANGELOG.md').read_text(), 'missing changelog version')
    for name in files:
        if not name.endswith('.md'):
            continue
        for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', (root/name).read_text()):
            if '://' in target or target.startswith('#'):
                continue
            target_path = (root/name).parent / target.split('#')[0]
            resolved = target_path.resolve()
            require(root.resolve() in resolved.parents and resolved.is_file(), f'broken local link: {name} -> {target}')
    agent = (root/'agents/openai.yaml').read_text()
    for key in ('icon_small', 'icon_large'):
        require(re.search(rf'^  {key}: assets/icon.svg$', agent, re.M), f'bad {key}')
    require('$dot-workflow' in agent, 'wrong invocation identity')
    svg = ET.fromstring((root/'assets/icon.svg').read_bytes())
    require(svg.tag == '{http://www.w3.org/2000/svg}svg', 'invalid SVG root')
    for node in svg.iter():
        require(node.tag.rsplit('}', 1)[-1] not in {'script', 'foreignObject'}, 'active SVG content')
        require(not any(k.rsplit('}', 1)[-1].startswith('on') or k.rsplit('}', 1)[-1] == 'href' for k in node.attrib), 'external or active SVG attribute')
    upstream = (root/'NOTICE.md').read_text()
    license_tail = upstream.split('## Third-party license\n\n')[-1]
    require('Copyright (c) 2026 Matt Pocock' in license_tail and license_tail.rstrip().endswith('SOFTWARE.'), 'missing upstream MIT notice')
    require((root/'LICENSE').read_text().startswith('MIT License\n'), 'missing project license')
    return version


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def build(commit, destination):
    require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None, 'use a full immutable commit SHA')
    require(git('rev-parse', f'{commit}^{{commit}}').decode().strip() == commit, 'not a commit')
    entries = git('ls-tree', '-rz', commit).split(b'\0')
    payload = {}
    for entry in filter(None, entries):
        header, raw_name = entry.split(b'\t', 1)
        mode, kind, _ = header.split()
        name = raw_name.decode()
        require(mode in {b'100644', b'100755'} and kind == b'blob', f'unsupported tree entry: {name}')
        require(name in SOURCE, f'unlisted committed file: {name}')
        payload[name] = git('show', f'{commit}:{name}')
    with tempfile.TemporaryDirectory(prefix='dot-workflow-check-') as directory:
        stage = Path(directory)
        for name, data in payload.items():
            path = stage/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        version = validate(stage)
    manifest = {'name': 'dot-workflow', 'version': version, 'commit': commit,
                'files': {name: {'bytes': len(payload[name]), 'sha256': sha256(payload[name])} for name in sorted(RUNTIME)}}
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination/'dot-workflow.zip'
    checksum = destination/'SHA256SUMS'
    require(not archive.exists() and not checksum.exists(), 'release outputs already exist; compare them before retrying')
    release = {name: payload[name] for name in RUNTIME}
    release['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode()
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in sorted(release.items()):
            info = zipfile.ZipInfo('dot-workflow/'+name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, data)
    digest = sha256(archive.read_bytes())
    checksum.write_text(f'{digest}  dot-workflow.zip\n')
    print(json.dumps({'version': version, 'commit': commit, 'sha256': digest, 'runtime_files': len(RUNTIME), 'archive': str(archive)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, help='output directory outside the source tree')
    parser.add_argument('--ref', help='full commit SHA for a release build')
    args = parser.parse_args()
    require(bool(args.build) == bool(args.ref), '--build and --ref must be used together')
    if args.build:
        build(args.ref, args.build.resolve())
    else:
        print(f'dot-workflow check: OK version={validate(ROOT)} source_files={len(SOURCE)} runtime_files={len(RUNTIME)}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, ET.ParseError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'dot-workflow check: ERROR: {error}')

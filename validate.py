"""Keep all private-source diagnostics off public Actions logs."""
import os, pathlib, subprocess, sys, zipfile
source = pathlib.Path(os.environ['RUNNER_TEMP']) / 'akscreen-source'
source.mkdir(exist_ok=True)
with zipfile.ZipFile(pathlib.Path(os.environ['RUNNER_TEMP']) / 'source.zip') as archive:
    for entry in archive.infolist():
        target = (source / entry.filename).resolve()
        if not target.is_relative_to(source.resolve()) or entry.file_size > 128 * 1024 * 1024:
            raise SystemExit('Invalid source snapshot')
    archive.extractall(source)
subprocess.run(['git', 'init', '-q'], cwd=source, check=True)
subprocess.run(['git', 'add', '.'], cwd=source, check=True)
log = pathlib.Path(os.environ['RUNNER_TEMP']) / 'diagnostics.log'
failed = False
def run(label, args):
    global failed
    print(label, flush=True)
    with log.open('ab') as output:
        output.write(('\n--- ' + label + ' ---\n').encode())
        result = subprocess.run(args, cwd=source, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        print('Failed; details are available in the encrypted diagnostics artifact.', flush=True)
        failed = True
    return result.returncode == 0
if os.environ.get('BUILD_MODE') == 'windows':
    run('Build Windows desktop', ['cargo', 'build', '--release', '--locked', '-p', 'filmcraft', '--bin', 'AKScreen'])
    if not failed:
        run('Desktop regression tests', ['cargo', 'test', '--release', '--locked', '-p', 'filmcraft', '--bin', 'AKScreen', 'akscreen::'])
        run('Package Windows installer', ['pwsh', '-File', 'packaging/akscreen/windows.ps1'])
else:
    if run('Resolve dependencies', ['cargo', 'generate-lockfile']):
        run('Format', ['cargo', 'fmt', '--all'])
        with (source / 'validation.patch').open('wb') as output:
            # Snapshots are not Git repositories; formatted sources are included below.
            output.write(b'')
        if run('Compile desktop', ['cargo', 'check', '--locked', '-p', 'filmcraft', '--bin', 'AKScreen']):
            for package in ['extensions', 'geom', 'project', 'format', 'engine', 'render', 'ui-egui']:
                run('Test ' + package, ['cargo', 'test', '--locked', '-p', 'filmcraft-' + package, '--lib'])
            run('Desktop tests', ['cargo', 'test', '--locked', '-p', 'filmcraft', '--bin', 'AKScreen', 'akscreen::'])
            for gate in ['layers', 'assets', 'wasm']:
                run('Check ' + gate, ['cargo', 'xtask', gate])
            run('Clippy', ['cargo', 'clippy', '--locked', '--workspace', '--all-targets', '--', '-D', 'warnings'])
with zipfile.ZipFile(pathlib.Path(os.environ['RUNNER_TEMP']) / 'result.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    if log.exists(): archive.write(log, 'diagnostics.log')
    if (source / 'Cargo.lock').exists(): archive.write(source / 'Cargo.lock', 'Cargo.lock')
    if os.environ.get('BUILD_MODE') == 'windows':
        for p in (source / 'dist/akscreen').glob('*'):
            if p.is_file(): archive.write(p, 'packages/' + p.name)
    else:
        for p in source.rglob('*.rs'):
            if not any(part in ('target', '.git', 'dist') for part in p.relative_to(source).parts):
                archive.write(p, 'formatted/' + p.relative_to(source).as_posix())
sys.exit(1 if failed else 0)

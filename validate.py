"""Keep all private-source diagnostics off public Actions logs."""
import os, pathlib, subprocess, sys, zipfile, time, urllib.request, hashlib, json
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
cached=pathlib.Path(os.environ['RUNNER_TEMP'])/'cached-result.zip'
if cached.exists():
    with zipfile.ZipFile(cached) as archive:
        for entry in archive.infolist():
            if not entry.filename.startswith('target/'):continue
            target=(source/entry.filename).resolve()
            if target.is_relative_to((source/'target').resolve()) and entry.file_size<512*1024*1024:archive.extract(entry,source)
# Actual, reviewed SDK binary exercises the component ABI; only public example source is fetched.
fixture_base='https://raw.githubusercontent.com/Edgajuman/AK-Screen-Extensions/e6e20b26e33df6013243fad36601af72f939a1fd/extensions/edgajuman/wasm-lab/1.0.0/'
manifest=json.loads(urllib.request.urlopen(fixture_base+'manifest.json',timeout=30).read())
component=urllib.request.urlopen(fixture_base+'component.wasm',timeout=30).read(64*1024*1024+1)
entry=manifest['files'][0]
if len(component)!=entry['size'] or hashlib.sha256(component).hexdigest()!=entry['sha256']:raise SystemExit('Public SDK fixture checksum failed')
fixture=source/'target/extension-fixture.wasm';fixture.parent.mkdir(exist_ok=True);fixture.write_bytes(component)
os.environ['AKSCREEN_EXTENSION_FIXTURE']=str(fixture)
log = pathlib.Path(os.environ['RUNNER_TEMP']) / 'diagnostics.log'
failed = False
def run(label, args):
    global failed
    print(label, flush=True)
    with log.open('ab') as output:
        output.write(('\n--- ' + label + ' ---\n').encode())
        process=subprocess.Popen(args,cwd=source,stdout=output,stderr=subprocess.STDOUT)
        started=time.monotonic()
        while process.poll() is None:
            try:process.wait(timeout=60)
            except subprocess.TimeoutExpired:print(label+' still running ('+str(round((time.monotonic()-started)/60))+' min)',flush=True)
    if process.returncode:
        print('Failed; details are available in the encrypted diagnostics artifact.', flush=True)
        failed = True
    return process.returncode == 0
if os.environ.get('BUILD_MODE') == 'windows':
    run('Build Windows desktop', ['cargo', 'build', '--release', '--locked', '--target', 'x86_64-pc-windows-msvc', '-p', 'filmcraft', '--bin', 'AKScreen'])
    if not failed:
        run('Desktop regression tests', ['cargo', 'test', '--release', '--locked', '--target', 'x86_64-pc-windows-msvc', '-p', 'filmcraft', '--bin', 'AKScreen', 'akscreen::'])
        run('Package Windows installer', ['pwsh', '-File', 'packaging/akscreen/windows.ps1'])
else:
    if run('Resolve dependencies', ['cargo', 'generate-lockfile']):
        run('Format', ['cargo', 'fmt', '--all'])
        with (source / 'validation.patch').open('wb') as output:
            # Snapshots are not Git repositories; formatted sources are included below.
            output.write(b'')
        if run('Compile desktop', ['cargo', 'check', '--locked', '-p', 'filmcraft', '--bin', 'AKScreen']):
            run('Apply reviewed lint fixes', ['cargo','clippy','--fix','--allow-dirty','--allow-staged','--workspace','--all-targets'])
            for package in ['extensions', 'geom', 'project', 'format', 'engine', 'render', 'export', 'ui-egui']:
                run('Test ' + package, ['cargo', 'test', '--locked', '-p', 'filmcraft-' + package, '--lib'])
            run('Desktop tests', ['cargo', 'test', '--locked', '-p', 'filmcraft', '--bin', 'AKScreen', 'akscreen::'])
            for gate in ['layers', 'assets', 'wasm']:
                run('Check ' + gate, ['cargo', 'xtask', gate])
            run('Clippy', ['cargo', 'clippy', '--locked', '--workspace', '--all-targets', '--', '-D', 'warnings'])
with zipfile.ZipFile(pathlib.Path(os.environ['RUNNER_TEMP']) / 'result.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    if log.exists(): archive.write(log, 'diagnostics.log')
    if (source / 'Cargo.lock').exists(): archive.write(source / 'Cargo.lock', 'Cargo.lock')
    for p in (source/'target').rglob('*'):
        if p.is_file() and p.stat().st_size<512*1024*1024 and not any(part in ('incremental',) for part in p.relative_to(source).parts):archive.write(p,p.relative_to(source).as_posix())
    if os.environ.get('BUILD_MODE') == 'windows':
        for p in (source / 'dist/akscreen').glob('*'):
            if p.is_file(): archive.write(p, 'packages/' + p.name)
    else:
        for p in source.rglob('*.rs'):
            if not any(part in ('target', '.git', 'dist') for part in p.relative_to(source).parts):
                archive.write(p, 'formatted/' + p.relative_to(source).as_posix())
sys.exit(1 if failed else 0)

"""VR-aware launcher backend. No stock installation or repair path is imported."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
import vr_language


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular(root, name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Invalid protected path')
    parts = name.split('/')
    if any(not p or p in ('.', '..') or ':' in p or p.endswith(('.', ' ')) for p in parts):
        raise ValueError('Invalid protected path')
    path = root
    for part in (None, *parts):
        if part is not None:
            path /= part
        st = path.lstat()
        if path.is_symlink() or getattr(st, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked launcher/runtime paths are not supported')
    if not path.is_file():
        raise ValueError('Missing protected file: ' + name)
    return path


def binding(package):
    package = Path(package).absolute()
    marker = json.loads(regular(package, 'vr-launcher.json').read_text(encoding='utf-8'))
    if marker.get('schema') != 1 or marker.get('profile') != 'vr-launcher-only-v1':
        raise ValueError('Invalid VR launcher binding')
    if package.parent.name != 'versions' or package.parent.parent.name != 'launcher-ui':
        raise ValueError('VR launcher must remain inside its versioned launcher-ui folder')
    root = package.parents[2]
    protection_path = regular(root, 'launcher-ui/vr-protection.json')
    if digest(protection_path) != marker.get('protection_sha256'):
        raise ValueError('VR protection record changed; rebind this launcher through the merge tool')
    protection = json.loads(protection_path.read_text(encoding='utf-8'))
    if protection.get('schema') != 1 or not isinstance(protection.get('files'), dict):
        raise ValueError('Invalid VR protection record')
    required = {'Test-VR.ps1', 'tools/launch_vr.ps1', 'runtime/darkwatch_xbe.exe',
                'runtime/darkwatch_xr_bridge.dll', 'runtime/openxr_loader.dll', 'runtime/vr-build.json'}
    if not required <= set(protection['files']):
        raise ValueError('Incomplete VR protection record')
    manifest = json.loads(regular(root, 'runtime/vr-build.json').read_text(encoding='utf-8'))
    if manifest.get('executable_sha256') != protection['files']['runtime/darkwatch_xbe.exe']:
        raise ValueError('VR executable identity does not match the bound runtime')
    return root, marker, protection


def verify(root, protection, full=False):
    critical = {'Test-VR.ps1', 'tools/launch_vr.ps1', 'runtime/darkwatch_xbe.exe',
                'runtime/darkwatch_xr_bridge.dll', 'runtime/openxr_loader.dll', 'runtime/vr-build.json'}
    names = protection['files'] if full else critical
    for name in names:
        pin = protection['files'][name]
        if not isinstance(pin, str) or not re.fullmatch('[0-9a-f]{64}', pin):
            raise ValueError('Invalid VR checksum')
        if digest(regular(root, name)) != pin:
            raise ValueError('Protected VR file changed: ' + name)


def status(root, package, diagnostics):
    return dict(installed=True, ready=True, update_available=False,
                hd_textures_installed=(root/'runtime/gameplay-hd').is_dir(),
                install_dir=str(root/'runtime'), source_mode='vr',
                diagnostic_logging=diagnostics.is_file(), diagnostics_dir=str(root/'sessions'),
                **vr_language.status(root/'runtime', package/'payload'),
                message='VR build ready. Play uses the preserved VR profile; launcher updates are separate.')


def launch(root, protection, cancel_file=None, runner=subprocess.run, diagnostic_logging=False):
    verify(root, protection)
    if cancel_file and Path(cancel_file).exists():
        raise ValueError('Launch cancelled before starting the game')
    # This command has no stock installer, asset preparation, display or save writes.
    shell = Path(os.environ.get('WINDIR', 'C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = [str(shell), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
               '-File', str(regular(root, 'Test-VR.ps1')), '-Launch']
    record_path = root/'tools/openxr-game-process.json'
    previous = record_path.stat().st_mtime_ns if record_path.exists() else None
    environment = os.environ.copy()
    for name in ('XBE_SESSION_LOG', 'XBE_SESSION_LOG_DIR'):
        environment.pop(name, None)
    if diagnostic_logging:
        environment.update(XBE_SESSION_LOG='1', XBE_SESSION_LOG_DIR=str(root/'sessions'))
    completed = runner(command, cwd=root, capture_output=True, text=True, env=environment,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout or 'VR profile failed')[-1000:])
    if not record_path.exists() or record_path.stat().st_mtime_ns == previous:
        raise ValueError('VR profile did not publish a new launch record')
    record = json.loads(regular(root, 'tools/openxr-game-process.json').read_text(encoding='utf-8-sig'))
    if (type(record.get('pid')) is not int or record['pid'] <= 0 or
            Path(record.get('exe', '')).absolute() != (root/'runtime/darkwatch_xbe.exe').absolute() or
            record.get('synthetic_input') is not False or record.get('openxr') is not True):
        raise ValueError('VR profile did not return a valid launch record')
    return record['pid']


class ReleaseAssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        url = urllib.parse.urlsplit(new_url)
        if (url.scheme != 'https' or url.netloc not in
                ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')):
            raise ValueError('Unexpected launcher download redirect.')
        return super().redirect_request(request, fp, code, message, headers, new_url)


def download_launcher(update, destination, cancel, notify):
    opener = urllib.request.build_opener(ReleaseAssetRedirect())
    request = urllib.request.Request(update['launcher_url'], headers={'User-Agent': 'Darkwatch-Darker-VR'})
    expected = update['launcher_size']
    total = 0
    with opener.open(request, timeout=20) as response, destination.open('xb') as output:
        while True:
            cancel()
            data = response.read(min(1024 * 1024, expected - total + 1))
            if not data:
                break
            total += len(data)
            if total > expected:
                raise ValueError('Launcher download exceeds its published size.')
            output.write(data)
            notify('progress', 'Downloading launcher update', percent=80 * total / expected)
    if total != expected or digest(destination) != update['launcher_sha256']:
        raise ValueError('Launcher download did not match its published checksum.')


def extract_launcher(archive, destination, layer, cancel):
    allowed = layer.REQUIRED | layer.LANGUAGE_PAYLOAD | {'bundle.json'}
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        names = {entry.filename for entry in members}
        if (len(names) != len(members) or names - allowed or
                sum(entry.file_size for entry in members) > 128 * 1024 * 1024):
            raise ValueError('Unexpected launcher update archive contents.')
        destination.mkdir()
        for entry in members:
            cancel()
            path = layer.safe(destination, entry.filename, exists=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as data, path.open('xb') as output:
                shutil.copyfileobj(data, output)
    return layer.validate_bundle(destination)


def install_launcher_update(root, package, protection, diagnostics, cancel, notify):
    import release_check
    verify(root, protection)
    manager = regular(root, 'tools/vr_launcher_layers.py')
    if digest(manager) != protection['files']['tools/vr_launcher_layers.py']:
        raise ValueError('The installed launcher update manager does not match its binding.')
    sys.path.insert(0, str(manager.parent))
    try:
        import vr_launcher_layers as layer
    finally:
        sys.path.pop(0)
    with vr_language.operation(root):
        current = layer.validate_active(root)
        if Path(current['entry']).parent != package:
            raise ValueError('This launcher is no longer active. Reopen it before updating.')
        update = release_check.check(package.name, vr=True)
        if not update.get('launcher_update'):
            raise ValueError('No verified launcher-only download is available.')
        version = layer.version(update['latest_version'])
        target = layer.safe(root, 'launcher-ui/versions/' + version, exists=False)
        if target.exists():
            raise ValueError('This launcher version already exists. Use launcher rollback or activation.')
        with tempfile.TemporaryDirectory(prefix='vr-update-', dir=root / 'launcher-ui') as directory:
            work = Path(directory)
            archive, bundle = work / 'launcher.zip', work / 'bundle'
            download_launcher(update, archive, cancel, notify)
            if extract_launcher(archive, bundle, layer, cancel)['version'] != version:
                raise ValueError('Launcher bundle version does not match the release.')
            cancel()
            vr_language.require_closed()
            notify('progress', 'Verifying and installing launcher files', percent=85)
            switched = False
            try:
                layer.install(root, bundle, apply=True)
                switched = True
                cancel()
                if diagnostics.is_file():
                    state = target / 'State'
                    state.mkdir()
                    (state / '.diagnostic-logging').touch()
                entry = layer.validate_active(root)['entry']
                subprocess.Popen([entry], cwd=target, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                if switched:
                    layer.activate(root, package.name)
                if target.exists():
                    failed = layer.safe(root, 'launcher-ui/versions/' + version).resolve()
                    if failed.parent == (root / 'launcher-ui/versions').resolve():
                        shutil.rmtree(failed)
                raise
    notify('release_ready', 'Launcher updated. Your VR installation was preserved.', percent=100)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--install-root', type=Path, required=True)
    parser.add_argument('--cancel-file', type=Path)
    parser.add_argument('--launcher-pid')
    parser.add_argument('--platform', default='windows')
    actions = parser.add_mutually_exclusive_group(required=True)
    for action in ['status', 'verify', 'play', 'check-updates', 'download-update', 'update', 'install-portuguese']:
        actions.add_argument('--'+action, action='store_true')
    actions.add_argument('--set-diagnostics', choices=('on', 'off'))
    actions.add_argument('--set-language', choices=('en', 'es', 'fr', 'de', 'it', 'pt-BR'))
    for action in ['import-iso', 'use-iso', 'use-installation', 'install-hd-textures',
                   'install-spanish', 'install-french', 'install-german', 'install-italian']:
        actions.add_argument('--'+action)
    args = parser.parse_args(argv)
    try:
        root, marker, protection = binding(args.package)
        if args.install_root.absolute() != (args.package/'State').absolute():
            raise ValueError('VR launcher state must stay inside this launcher version')
        if args.check_updates:
            import release_check
            result = release_check.check(args.package.name, 'windows', vr=True)
            print(json.dumps(dict(result, event='release_check')))
            return 0
        state = vr_language.checked(args.package, 'State')
        diagnostics = vr_language.checked(state, '.diagnostic-logging')
        runtime = root/'runtime'
        payload = args.package/'payload'

        def cancel():
            if args.cancel_file and args.cancel_file.exists():
                raise ValueError('Launcher operation cancelled.')

        def notify(event, message, **fields):
            print(json.dumps(dict(event=event, message=message, **fields)), flush=True)

        if args.download_update:
            install_launcher_update(root, args.package, protection, diagnostics, cancel, notify)
            return 0

        install_code, iso = next(((code, iso) for code, iso in (
            ('es', args.install_spanish), ('fr', args.install_french),
            ('de', args.install_german), ('it', args.install_italian),
            ('pt-BR', args.install_portuguese),
        ) if iso), (None, None))
        if not (args.status or args.verify or args.play or args.set_diagnostics or args.set_language or install_code):
            raise ValueError('This action would modify the VR installation. Use the isolated VR source-merge/update process; files were not changed.')
        verify(root, protection, full=args.verify)
        if args.set_diagnostics:
            state.mkdir(exist_ok=True)
            if args.set_diagnostics == 'on':
                diagnostics.touch()
            else:
                diagnostics.unlink(missing_ok=True)
        if args.set_language or install_code:
            with vr_language.operation(root):
                if args.set_language:
                    vr_language.select(runtime, payload, args.set_language, cancel)
                else:
                    vr_language.install(runtime, payload, state, install_code, iso, cancel, notify)
        result = status(root, args.package, diagnostics)
        if args.play:
            with vr_language.operation(root):
                code = result['language']
                if code != 'en' and not vr_language.catalog(payload, code).validate(runtime, cancel):
                    raise ValueError('Repair the selected language or choose English before starting VR.')
                result['pid'] = launch(root, protection, args.cancel_file, diagnostic_logging=diagnostics.is_file())
            result['message'] = 'Darkwatch VR started with the preserved controller and rendering profile.'
        elif args.verify:
            result['message'] = 'Protected VR runtime, profiles and assets verified. No files changed.'
        elif args.set_diagnostics:
            result['message'] = 'Diagnostic logging applies to the next VR session.'
        elif args.set_language:
            result['message'] = 'Selected language applies to the next VR session.'
        elif install_code:
            result['message'] = 'Language installed. Select it before starting VR.'
        print(json.dumps(dict(result, event='status' if args.status else 'result', percent=100)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print(json.dumps(dict(event='error', ready=False, message=str(error))))
        return 1


if __name__ == '__main__':
    sys.exit(main())

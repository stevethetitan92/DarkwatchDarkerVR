"""Install versioned, VR-aware launcher UI bundles; never write the game runtime."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil

PROFILE = 'vr-launcher-only-v1'
PYTHON_FILES = {'python.exe','python312.dll','python3.dll','python312.zip','python312._pth',
                'vcruntime140.dll','vcruntime140_1.dll','_hashlib.pyd','libcrypto-3.dll',
                '_ssl.pyd','libssl-3.dll','_socket.pyd','select.pyd','unicodedata.pyd',
                '_ctypes.pyd','libffi-8.dll','LICENSE.txt'}
REQUIRED = {'Darkwatch Darker Edition.exe','Play Darkwatch.exe','payload/vr_launcher_backend.py',
            'payload/release_check.py'} | {'payload/python/'+n for n in PYTHON_FILES}
LANGUAGE_FILES = {
    'vr_language.py', 'language_pack.py', 'gameplay_hd.py', 'intake.py',
    'character_archive.py', 'character_assets.py',
    'ps2_spanish.py', 'ps2_disc.py', 'ps2_dialogue.py', 'ps2_movies.py', 'ps2_text.py',
    'portuguese-catalog.json', 'portuguese-text.zip',
} | {f'ps2-{language}-{kind}.json'
     for language in ('spanish', 'french', 'german', 'italian')
     for kind in ('catalog', 'corrections')}
LANGUAGE_PAYLOAD = {'payload/' + name for name in LANGUAGE_FILES}


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def safe(root, name='', exists=True):
    parts = name.split('/') if name else []
    if any(not n or n in ('.','..') or '\\' in n or ':' in n or n.endswith(('.', ' ')) for n in parts):
        raise ValueError('Invalid layer path')
    p = Path(root).absolute()
    for part in (None,*parts):
        if part is not None:
            p /= part
        if p.exists() or p.is_symlink():
            if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400:
                raise ValueError('Linked layer path')
    if exists and not p.exists():
        raise ValueError('Missing layer path: '+str(p))
    return p


def version(v):
    if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',v) or '..' in v:
        raise ValueError('Invalid version directory')
    return v


def validate_bundle(bundle):
    data=json.loads(safe(bundle,'bundle.json').read_text(encoding='utf-8'))
    if data.get('schema')!=1 or data.get('profile')!=PROFILE:
        raise ValueError('Only reviewed VR launcher bundles are supported; stock packages cannot be overlaid')
    version(data.get('version'))
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',data.get('upstream_version','')):
        raise ValueError('Invalid upstream version')
    allowed=set(data.get('files',{}))
    if allowed not in (REQUIRED, REQUIRED | LANGUAGE_PAYLOAD):
        raise ValueError('Launcher bundle allowlist mismatch')
    actual={p.relative_to(bundle).as_posix() for p in Path(bundle).rglob('*') if p.is_file() and not p.relative_to(bundle).as_posix().startswith('State/')}
    if actual != allowed | {'bundle.json'} | ({'vr-launcher.json'} if (Path(bundle)/'vr-launcher.json').exists() else set()):
        raise ValueError('Unlisted bundle files')
    for name,h in data['files'].items():
        if not re.fullmatch('[0-9a-f]{64}',str(h)) or sha(safe(bundle,name))!=h:
            raise ValueError('Bundle checksum mismatch: '+name)
    return data


def snapshot(root):
    root=safe(root)
    required=['runtime','tools','Test-VR.ps1','Test-Combat-VR.ps1','vr-build.json']
    if (root/'Open-VR-Launcher.ps1').exists():required.append('Open-VR-Launcher.ps1')
    files={}
    for name in required:
        p=safe(root,name)
        candidates=p.rglob('*') if p.is_dir() else [p]
        for f in candidates:
            if f.is_file():
                rel=f.relative_to(root).as_posix();files[rel]=sha(safe(root,rel))
    return files


def protection(root, before):
    # Mutable saves, logs, settings and caches are preserved by the installer but
    # cannot be pinned for all future game sessions. Runtime code/art stays pinned.
    files={n:h for n,h in before.items() if n in ('Test-VR.ps1','Test-Combat-VR.ps1','vr-build.json','Open-VR-Launcher.ps1') or
           (n.startswith('tools/') and n.endswith(('.py','.ps1','.json')) and not n.endswith('openxr-game-process.json')) or
           (n.startswith('runtime/') and not n.startswith(('runtime/hdd/','runtime/hdd2/','runtime/logs/','runtime/cache/','runtime/language/')) and
            not n.endswith('darkwatch_xbe_settings.toml') and not n.endswith('.pdb'))}
    return {'schema':1,'profile':PROFILE,'files':dict(sorted(files.items()))}


def activate(root, target_version):
    root=safe(root);target_version=version(target_version)
    package=safe(root,'launcher-ui/versions/'+target_version)
    data=validate_bundle(package)
    marker=json.loads(safe(package,'vr-launcher.json').read_text())
    if marker.get('schema')!=1 or marker.get('profile')!=PROFILE or marker.get('upstream_version')!=data['upstream_version']:
        raise ValueError('Invalid installed VR launcher binding')
    if marker.get('protection_sha256')!=sha(safe(root,'launcher-ui/vr-protection.json')):
        raise ValueError('Version is bound to a different VR runtime')
    pointer={'schema':1,'version':target_version,'entry_sha256':data['files']['Darkwatch Darker Edition.exe'],
             'bundle_sha256':sha(package/'bundle.json'),'marker_sha256':sha(package/'vr-launcher.json')}
    layer=safe(root,'launcher-ui');temp=layer/'active.json.tmp'
    temp.write_text(json.dumps(pointer,indent=2)+'\n',encoding='utf-8')
    os.replace(temp,layer/'active.json')
    return pointer


def install(root, bundle, apply=False, copy=shutil.copy2):
    root=safe(root);bundle=safe(bundle);data=validate_bundle(bundle)
    before=snapshot(root)
    result={'version':data['version'],'files':len(data['files']),'protected_files':len(before),'applied':False,'game_launched':False}
    if not apply:
        return result
    dest=safe(root,'launcher-ui/versions/'+data['version'],exists=False)
    if dest.exists():
        raise ValueError('Version already exists; use activate to roll back or build a new version')
    dest.mkdir(parents=True)
    for name in sorted(set(data['files'])|{'bundle.json'}):
        p=safe(dest,name,exists=False);p.parent.mkdir(parents=True,exist_ok=True);copy(safe(bundle,name),p)
    # Validate contents before adding the local binding file.
    validate_bundle(dest)
    record=protection(root,before);record_bytes=(json.dumps(record,indent=2)+'\n').encode('utf-8')
    protection_path=root/'launcher-ui/vr-protection.json'
    if protection_path.exists() and protection_path.read_bytes()!=record_bytes:
        raise ValueError('Existing launcher protection differs; stage a separately reviewed runtime merge first')
    protection_path.write_bytes(record_bytes)
    marker={'schema':1,'profile':PROFILE,'upstream_version':data['upstream_version'],
            'protection_sha256':sha(protection_path)}
    (dest/'vr-launcher.json').write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8')
    if snapshot(root)!=before:
        raise ValueError('Protected files changed during staging; active launcher was not switched')
    result.update(applied=True,active=activate(root,data['version']),protected_files_unchanged=True)
    return result


def validate_active(root):
    root=safe(root)
    pointer=json.loads(safe(root,'launcher-ui/active.json').read_text(encoding='utf-8'))
    if pointer.get('schema')!=1:raise ValueError('Invalid launcher pointer')
    v=version(pointer.get('version'));package=safe(root,'launcher-ui/versions/'+v)
    data=validate_bundle(package)
    for key,name in [('entry_sha256','Darkwatch Darker Edition.exe'),('bundle_sha256','bundle.json'),('marker_sha256','vr-launcher.json')]:
        if pointer.get(key)!=sha(safe(package,name)):raise ValueError('Active launcher identity changed')
    marker=json.loads(safe(package,'vr-launcher.json').read_text())
    if marker.get('schema')!=1 or marker.get('profile')!=PROFILE or marker.get('protection_sha256')!=sha(safe(root,'launcher-ui/vr-protection.json')):
        raise ValueError('Active launcher is not bound to this protected runtime')
    return {'version':v,'entry':str(package/'Darkwatch Darker Edition.exe'),'game_launched':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--bundle',type=Path);p.add_argument('--activate');p.add_argument('--validate-active',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args()
    if sum([bool(a.bundle),bool(a.activate),a.validate_active])!=1:p.error('Choose --bundle, --activate or --validate-active')
    if a.activate and not a.apply:p.error('Activation requires --apply')
    try:print(json.dumps(validate_active(a.root) if a.validate_active else install(a.root,a.bundle,a.apply) if a.bundle else activate(a.root,a.activate),indent=2))
    except (OSError,ValueError,KeyError,TypeError) as e:p.exit(1,str(e)+'\n')


if __name__=='__main__':main()

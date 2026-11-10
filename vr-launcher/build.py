from pathlib import Path
import argparse,json,shutil,subprocess,os,sys
src = Path(__file__).resolve().parent
repo = src.parent
sys.path.insert(0, str(src))
import vr_launcher_layers as layer

parser = argparse.ArgumentParser(description='Build the VR launcher-only bundle')
parser.add_argument('--python-dir', type=Path, required=True, help='Unpacked Windows x64 Python 3.12 embeddable distribution')
parser.add_argument('--output', type=Path, required=True, help='New bundle directory named for its launcher version')
options = parser.parse_args()
bundle = options.output.resolve()
version = layer.version(bundle.name)
python = options.python_dir.resolve()
assets = repo/'launcher/assets'
for name in layer.PYTHON_FILES:
 if not (python/name).is_file():
  parser.error('Missing embedded Python file: ' + name)
bundle.mkdir(parents=True)
framework=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319'
refs=['System.dll','System.Core.dll','System.Xaml.dll','System.Web.Extensions.dll','System.Windows.Forms.dll','WPF/PresentationFramework.dll','WPF/PresentationCore.dll','WPF/WindowsBase.dll']
args=[str(framework/'csc.exe'),'/nologo','/target:winexe','/platform:x64','/optimize+',
 '/win32icon:'+str(assets/'insignia.ico'),'/win32manifest:'+str(src/'app.manifest'),
 '/resource:'+str(assets/'cover-darker-edition.png')+',Darkwatch.Cover.png',
 '/resource:'+str(assets/'insignia.png')+',Darkwatch.Insignia.png',
 '/resource:'+str(src/'MainWindow.xaml')+',Darkwatch.MainWindow.xaml']+['/reference:'+str(framework/n) for n in refs]
for name,sources,defines in [('Darkwatch Darker Edition.exe',['Launcher.cs','SetupProcess.cs'],[]),('Play Darkwatch.exe',['DirectPlay.cs','Launcher.cs','SetupProcess.cs'],['/define:DIRECT_PLAY'])]:
 p=subprocess.run(args+defines+['/out:'+str(bundle/name)]+[str(src/n) for n in sources],capture_output=True,text=True)
 print(name,p.returncode,p.stdout,p.stderr,flush=True)
 if p.returncode:raise RuntimeError('Launcher compile failed')
for name in layer.PYTHON_FILES:
 d=bundle/'payload/python'/name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(python/name,d)
for name in ['vr_launcher_backend.py','release_check.py']:
 shutil.copy2(src/name,bundle/'payload'/name)
language_payload=set()
if (src/'vr_language.py').is_file():
 for name in sorted(layer.LANGUAGE_FILES):
  source = (repo/'tools/intake.py' if name=='intake.py' else
            src/name if name=='vr_language.py' else repo/'launcher'/name)
  shutil.copy2(source,bundle/'payload'/name)
 language_payload=layer.LANGUAGE_PAYLOAD
files={p.relative_to(bundle).as_posix():layer.sha(p) for p in bundle.rglob('*') if p.is_file()}
assert set(files)==layer.REQUIRED|language_payload
manifest={'schema':1,'profile':layer.PROFILE,'version':version,'upstream_version':'0.7.8','files':files}
(bundle/'bundle.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print('Built launcher-only bundle',len(files),'files;no game executable or game assets packaged')

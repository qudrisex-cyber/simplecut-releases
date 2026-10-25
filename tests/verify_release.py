"""Anonymous public downloads -> real installed EXE -> package activation on Windows.
The installed BASE version is lowered only in this disposable test installation.
No distributed asset is altered and no credentials are used.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
import zipfile

REPO='qudrisex-cyber/simplecut-releases'
MANIFEST=f'https://github.com/{REPO}/releases/latest/download/update.json'
EVIDENCE=Path('evidence');EVIDENCE.mkdir(exist_ok=True)

def download(url,path,limit):
    request=urllib.request.Request(url,headers={'User-Agent':'SimpleCut-Public-Verification'})
    with urllib.request.urlopen(request,timeout=40) as response,open(path,'wb') as out:
        assert response.geturl().startswith('https://')
        size=0
        while True:
            block=response.read(65536)
            if not block:break
            size+=len(block)
            if size>limit:raise ValueError('Download exceeds expected limit')
            out.write(block)
    return size

def smoke(exe,label):
    report=(EVIDENCE/f'{label}.json').resolve()
    subprocess.run([str(exe),'--self-test',str(report)],check=True,timeout=180)
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['ok'] and data['frozen'],data
    return data

with tempfile.TemporaryDirectory(prefix='SimpleCut-public-test-') as td:
    root=Path(td);manifest_path=root/'update.json'
    download(MANIFEST,manifest_path,65536)
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    version=manifest['version'];assert re.fullmatch(r'\d+\.\d+\.\d+',version)
    expected=f'https://github.com/{REPO}/releases/download/v{version}/SimpleCut-{version}-update.zip'
    assert manifest['url']==expected
    package=root/'downloaded-update.zip';size=download(expected,package,16*1024*1024)
    sha=hashlib.sha256(package.read_bytes()).hexdigest()
    assert size==manifest['size'] and sha==manifest['sha256']
    with zipfile.ZipFile(package) as z:
        info=json.loads(z.read('package.json'))
        assert info['version']==version and info['runtime']==manifest['runtime']
        assert set(z.namelist())=={'package.json','app.py','core.py','player.py','update_ui.py'}
    installer=root/'Setup.exe'
    download(f'https://github.com/{REPO}/releases/download/v{version}/SimpleCut-{version}-Setup.exe',installer,250*1024*1024)
    sums=root/'SHA256SUMS.txt'
    download(f'https://github.com/{REPO}/releases/download/v{version}/SHA256SUMS.txt',sums,65536)
    hashes={line.split()[1]:line.split()[0] for line in sums.read_text(encoding='utf-8-sig').splitlines() if line.strip()}
    assert hashes[f'SimpleCut-{version}-Setup.exe']==hashlib.sha256(installer.read_bytes()).hexdigest()
    assert hashes[f'SimpleCut-{version}-update.zip']==sha
    if 'application.zip' in hashes:
        recovery=root/'application.zip'
        download(f'https://github.com/{REPO}/releases/download/v{version}/application.zip',recovery,16*1024*1024)
        assert recovery.read_bytes()==package.read_bytes()
        assert hashes['application.zip']==sha
    installed=root/'installed';exe=installed/'SimpleCut.exe'
    subprocess.run([str(installer),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TASKS=',f'/DIR={installed}'],check=True,timeout=180)
    try:
        first=smoke(exe,'public-installed');assert first['version']==version
        channel=json.loads((installed/'update-channel.json').read_text(encoding='utf-8'))
        assert channel['manifest_url']==MANIFEST
        base=installed/'application.zip';lowered=root/'test-base.zip'
        with zipfile.ZipFile(base) as src,zipfile.ZipFile(lowered,'w',zipfile.ZIP_DEFLATED) as out:
            for name in src.namelist():
                data=src.read(name)
                if name=='package.json':
                    metadata=json.loads(data);metadata['version']='0.0.0';data=json.dumps(metadata).encode()
                elif name=='app.py':
                    needle=f"VERSION='{version}'".encode();assert needle in data
                    data=data.replace(needle,b"VERSION='0.0.0'",1)
                out.writestr(name,data)
        os.replace(lowered,base)
        updates=installed/'updates';updates.mkdir(exist_ok=True)
        (updates/f'{sha}.zip').write_bytes(package.read_bytes())
        (installed/'update-state.json').write_text(json.dumps({'active':'base','pending':sha,'trial':False}),encoding='utf-8')
        updated=smoke(exe,'public-package-activated')
        assert updated['version']==version and 'updates' in updated['application_module']
        assert smoke(exe,'public-package-second-launch')['version']==version
        (EVIDENCE/'public-channel.json').write_text(json.dumps({'ok':True,'manifest_url':MANIFEST,'version':version,'package_bytes':size,'sha256':sha,'checks':['anonymous-manifest','anonymous-package','package-size-and-hash','installer-checksum','real-install','embedded-channel','real-frozen-package-activation','second-launch','ffmpeg-exports'],'test_baseline':'Disposable installed base lowered to 0.0.0; published files unchanged'},indent=2),encoding='utf-8')
        print(f'PASS: public channel, real Windows install and activation of downloaded {size}-byte package')
    finally:
        subprocess.run([str(installed/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True,timeout=180)

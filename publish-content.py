"""Publish reviewed data only. Never execute code from the control or extension repositories."""
import hashlib, json, pathlib, re, shutil, sys, time, zipfile
control, community, downloads, site = map(pathlib.Path,sys.argv[1:5])
base='https://edgajuman.github.io/'
def safe(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,95}',value)) and '..' not in value
def local(root,value):
    if not isinstance(value,str) or '\\' in value or ':' in value: raise ValueError('Unsafe path')
    original=root/value
    if original.is_absolute() and not original.is_relative_to(root): raise ValueError('Unsafe attachment')
    if any(p.is_symlink() for p in [original,*original.parents] if p!=root.parent): raise ValueError('Symlink not permitted')
    path=original.resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file(): raise ValueError('Unsafe attachment')
    return path
def copy_once(source,dest):
    if source.stat().st_size>64*1024*1024: raise ValueError('Attachment too large')
    data=source.read_bytes()
    if dest.exists() and dest.read_bytes()!=data: raise ValueError('Published version is immutable')
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    return {'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
def packet(folder,out):
    manifest=json.loads(local(folder,'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema')!=1 or manifest.get('sdk')!=1 or not safe(manifest.get('id')): raise ValueError('Unsupported manifest')
    version=manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?',version): raise ValueError('Invalid version')
    files=manifest.get('files',[])
    if len(files)>256: raise ValueError('Too many files')
    allowed={'.wasm','.json','.md','.png','.jpg','.jpeg','.gif','.webp','.svg','.txt'}
    total=0;contents=[];seen=set()
    for item in files:
        p=local(folder,item['path']);total+=p.stat().st_size
        if total>64*1024*1024 or p.suffix.lower() not in allowed or item['path'].lower() in seen or item['path'].lower()=='manifest.json': raise ValueError('Unsafe package')
        seen.add(item['path'].lower());data=p.read_bytes()
        if len(data)!=item['size'] or hashlib.sha256(data).hexdigest()!=item['sha256']: raise ValueError('Package checksum mismatch')
        if p.suffix.lower()=='.wasm' and not data.startswith(b'\0asm'): raise ValueError('Only binary Wasm components')
        if p.suffix.lower()=='.svg' and re.search(rb'<!DOCTYPE|<!ENTITY|<script|(?:href|src)\s*=\s*[\x22\x27](?:https?:|file:|/)',data,re.I): raise ValueError('External SVG resource')
        contents.append((item['path'],data))
    out.parent.mkdir(parents=True,exist_ok=True)
    import io
    buffer=io.BytesIO()
    # Reproducible archives keep the immutable version checksum stable across publication runs.
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in [('manifest.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())]+contents:
            info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            archive.writestr(info,data)
    data=buffer.getvalue()
    if out.exists() and out.read_bytes()!=data: raise ValueError('Changing an existing version is not allowed')
    if len(data)>64*1024*1024:raise ValueError('Package archive too large')
    out.write_bytes(data)
    return {'manifest':manifest,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}

spec=json.loads(local(control,'feed.json').read_text(encoding='utf-8'))
if len(spec.get('notices',[]))>128: raise ValueError('Too many notices')
feed={'schema':1,'generation':0,'published':0,'notices':[],'packages':[],'withdrawn':spec.get('withdrawn',[])}
target=downloads/'content';target.mkdir(exist_ok=True)
for source in spec.get('notices',[]):
    if not source.get('published',False): continue
    n={k:v for k,v in source.items() if k not in ('published','markdown_file','media')}
    if not safe(n['id']) or not isinstance(n['revision'],int) or n['revision']<1: raise ValueError('Invalid notice identity')
    text=local(control,source['markdown_file']).read_text(encoding='utf-8')
    if len(text.encode())>65536: raise ValueError('Notice too large')
    # Safe subset of GitHub's pasted video markup; no other HTML is published as executable UI.
    text=re.sub(r'<video\b[^>]*\bsrc=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*>\s*</video>',lambda m:'[Reproducir video]('+m[1]+')',text,flags=re.I)
    n['markdown']=text;n['media']=[]
    for media in source.get('media',[]):
        p=local(control,media['path']);kind=media['kind'];ext=p.suffix.lower()
        if kind not in ('image','gif','video') or ext not in ('.png','.jpg','.jpeg','.gif','.webp','.mp4','.webm','.mov'): raise ValueError('Unsupported media')
        relative='media/'+n['id']+'/'+str(n['revision'])+'/'+p.name
        info=copy_once(p,target/relative)
        n['media'].append({'path':media['path'],'kind':kind,'url':base+'AKScreen-Downloads/content/'+relative,**info})
    feed['notices'].append(n)
catalogue={'schema':1,'releases':[],'revoked':json.loads((community/'revoked.json').read_text()) if (community/'revoked.json').exists() else []}
for manifest in sorted((community/'extensions').glob('*/*/*/manifest.json')):
    m=json.loads(manifest.read_text(encoding='utf-8'));path='packages/'+m['id']+'/'+m['version']+'.akext'
    release=packet(manifest.parent,site/path);release['url']=base+'AK-Screen-Extensions/'+path
    catalogue['releases'].append(release)
for manifest in sorted((control/'packages').glob('*/*/manifest.json')):
    m=json.loads(manifest.read_text(encoding='utf-8'));path='packages/'+m['id']+'/'+m['version']+'.akext'
    release=packet(manifest.parent,target/path);release['url']=base+'AKScreen-Downloads/content/'+path;feed['packages'].append(release)
if len(catalogue['releases'])>512 or len(feed['packages'])>128: raise ValueError('Catalogue too large')
# Preserve previous signatures when content did not change, avoiding unnecessary commits.
def stage(payload,path,output,notice=False):
    old={}
    if path.exists():old=json.loads(json.loads(path.read_text(encoding='utf-8'))['payload'])
    previous={k:v for k,v in old.items() if k not in ('generation','published')}
    current={k:v for k,v in payload.items() if k not in ('generation','published')}
    if previous==current:return
    if notice:payload['generation']=old.get('generation',0)+1;payload['published']=int(time.time())
    output.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
stage(feed,target/'feed.json',downloads/'feed-payload.json',True)
stage(catalogue,site/'catalogue.json',site/'catalogue-payload.json')
print('Validated reviewed content and immutable packages')

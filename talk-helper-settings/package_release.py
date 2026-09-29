from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json,os
root=Path(__file__).resolve().parent
release_bin=Path(os.environ.get('TALKHELPER_RELEASE_BIN',root/'bin'))
bundle=root/'TalkHelper-Portable-v13r2.7.zip'
config=dict(relationship='朋友',context=12,model_provider='deepseek',reply_target=False,
            style='建议具体、自然、可执行，结合聊天上下文，不臆测对方心理。',common_phrases='',assistant_name='talk helper',
            thinking=False,check_update=False,deepseek_base_url='https://api.deepseek.com',deepseek_model='deepseek-flash')
with ZipFile(bundle,'w',ZIP_DEFLATED,compresslevel=6) as z:
    for name in ('TalkHelper-Native-v13.exe','TalkHelper-Stop-v13r2.exe','TalkHelper-Settings-v13.exe','TalkHelperNative-v13r2.dll'):
        z.write(release_bin/name,name)
    for name in ('README.md','VALIDATION.md','VALIDATION-v13r2.5.md','LICENSE.wechatauto.txt','THIRD_PARTY_NOTICE.md'):
        z.write(root/name,name)
    z.writestr('config.json',json.dumps(config,ensure_ascii=False,indent=2))
    for path in sorted((release_bin/'TalkHelperNativeWorker-v13r2').rglob('*')):
        if path.is_file():z.write(path,path.relative_to(release_bin).as_posix())
with ZipFile(bundle) as z:
    names=z.namelist()
    assert not any('chat-selection' in n or 'runtime-status' in n or n.endswith(('.db','.jpg','.png')) for n in names)
print(f'{bundle.name}: {bundle.stat().st_size} bytes; {len(names)} files; user data excluded')

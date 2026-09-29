"""Per-account, fail-closed selection. Stores identifiers and display names only."""
import json,threading
from pathlib import Path

class ChatSelection:
    def __init__(self,path,account):
        self.path=Path(path);self.account=str(account or '');self.lock=threading.RLock();self.data={'schema':1,'accounts':{}}
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('schema')==1 and isinstance(data.get('accounts'),dict):self.data=data
        except (OSError,ValueError,TypeError):pass
    @property
    def selected(self):
        with self.lock:
            result=self.data['accounts'].get(self.account,{})
            return dict(result) if isinstance(result,dict) and self.account else {}
    def enabled(self,username):return bool(username and username in self.selected)
    def set(self,username,name,enabled):
        if not self.account or not isinstance(username,str) or not username or len(username)>128:raise ValueError('Unverified chat')
        with self.lock:
            values=self.data['accounts'].setdefault(self.account,{})
            if enabled:values[username]=str(name or username)[:128]
            else:values.pop(username,None)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)

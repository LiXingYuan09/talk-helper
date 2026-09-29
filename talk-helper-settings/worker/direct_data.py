"""Read only the chat databases needed for a visible WeChat conversation.

The key material stays in memory. Decrypted snapshots live in a temporary
directory owned by the worker and are removed on normal shutdown.
"""
from __future__ import annotations

import os
import re

from wechat_db import WeChatDB


class ConversationDB(WeChatDB):
    NAMES = {"contact.db", "session.db", "message_0.db", "message_1.db",
             "message_resource.db"}

    def __init__(self, *args, wechat_pid: int, **kwargs):
        self.wechat_pid = int(wechat_pid)
        super().__init__(*args, **kwargs)

    def _find_weixin_pids(self):
        return [self.wechat_pid]

    def _collect_db_files(self):
        return [entry for entry in super()._collect_db_files()
                if os.path.basename(entry[1]) in self.NAMES
                or re.fullmatch(r"message_\d+\.db", os.path.basename(entry[1]))]

    def _stable_key_file(self, account=None):
        return None

    def _save_keys(self):
        # Never persist decrypted WeChat keys.
        pass

    def _shard_rows(self, tables, *args, **kwargs):
        # real_sender_id belongs to this message shard's Name2Id, not to
        # message_resource.SenderName2Id. Keep the mapping with each row.
        rows = []
        for conn, table in tables:
            names = dict(conn.execute('SELECT rowid, user_name FROM Name2Id'))
            for raw in super()._shard_rows([(conn, table)], *args, **kwargs):
                row = dict(raw)
                row['_shard_sender_username'] = names.get(row['real_sender_id'], '')
                rows.append(row)
        return rows

    def resolve_chat(self, title: str):
        """Resolve only an unambiguous, exact contact or group display name."""
        title = (title or "").strip()
        if not title or len(title) > 128:
            return None
        # Search-contact's LIKE/LIMIT 50 can miss short or wildcard nicknames.
        # WeChat displays the remark in preference to the nickname.
        matches=set()
        for rel,path,_ in self._db_files:
            if os.path.basename(path)!='contact.db':continue
            conn=self._open(rel)
            try:
                matches.update(user for user, in conn.execute(
                    "SELECT username FROM contact WHERE "
                    "COALESCE(NULLIF(TRIM(remark),''),NULLIF(TRIM(nick_name),''),username)=?",(title,)))
            finally:conn.close()
        if len(matches)>1 and len(matches)<=64:
            # Duplicate address-book nicknames are common. The visible chat
            # list can still identify one non-hidden conversation uniquely.
            sessions=set()
            for rel,path,_ in self._db_files:
                if os.path.basename(path)!='session.db':continue
                conn=self._open(rel)
                try:
                    marks=','.join('?' for _ in matches)
                    sessions.update(user for user, in conn.execute(
                        f'SELECT username FROM SessionTable WHERE is_hidden=0 AND username IN ({marks})',tuple(matches)))
                finally:conn.close()
            matches=sessions
        return next(iter(matches)) if len(matches) == 1 else None

    def _msg_row_to_dict(self,row):
        result=super()._msg_row_to_dict(row)
        sender=result.get('sender_username')
        result['is_self']=(sender==self.wxid) if sender else result['sender_id']==2
        return result

    def enrich_profiles(self, username, records):
        """Read identities and cached avatar bytes locally; never fetch URLs."""
        people = set()
        for record in records:
            sender = record.get('sender_username') or (self.wxid if record['sender_id']==2 else username)
            if sender and not sender.endswith('@chatroom'):people.add(sender)
        profiles = {person: {'name':'', 'avatar':b''} for person in people}
        if people:
            placeholders=','.join('?' for _ in people);params=tuple(people)
            for rel,path,_ in self._db_files:
                kind=os.path.basename(path)
                if kind not in ('contact.db','head_image.db'):continue
                conn=self._open(rel)
                try:
                    if kind=='contact.db':
                        for person,nick,remark in conn.execute('SELECT username,nick_name,remark FROM contact WHERE username IN ('+placeholders+')',params):
                            profiles[person]['name']=remark or nick or ''
                    else:
                        for person,blob in conn.execute('SELECT username,image_buffer FROM head_image WHERE username IN ('+placeholders+')',params):
                            if isinstance(blob,bytes) and len(blob)<=65536 and (blob.startswith(b'\xff\xd8\xff') or blob.startswith(b'\x89PNG\r\n\x1a\n')):
                                profiles[person]['avatar']=blob
                finally:conn.close()
        for record in records:
            sender=record.get('sender_username') or (self.wxid if record['sender_id']==2 else username)
            profile=profiles.get(sender,{})
            record['display_name']=profile.get('name') or ('我' if record['sender_id']==2 else '群成员' if username.endswith('@chatroom') else '')
            record['avatar']=profile.get('avatar',b'')
        return records

    def chat_directory(self):
        sessions=self.get_sessions(limit=3000)
        names={}
        for rel,path,_ in self._db_files:
            if os.path.basename(path)!='contact.db':continue
            conn=self._open(rel)
            try:
                names={user:remark or nick or user for user,nick,remark in conn.execute('SELECT username,nick_name,remark FROM contact')}
            finally:conn.close()
        seen=set();items=[]
        for username in [s['username'] for s in sessions]+sorted(names,key=lambda u:names[u].casefold()):
            if not username or username in seen or username==self.wxid:continue
            seen.add(username);items.append({'username':username,'name':names.get(username,username),'group':username.endswith('@chatroom')})
        return items[:3000]

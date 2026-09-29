The file `worker/wechat_db.py` is adapted from `wechatauto/db.py` in
[fanyuantaier/wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica),
commit `c350cd66a1e23711e2089c03473aaaf8b42cff41`, licensed under Apache 2.0.
The adaptation replaces its logger import with Python's standard logging and
allows an explicitly supplied per-shard sender mapping for decoded messages.
The application subclasses the reader to limit the databases accessed and
prevent key files from being written. The full upstream license is included in
`LICENSE.wechatauto.txt`.

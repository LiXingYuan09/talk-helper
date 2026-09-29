"""Select exact, reviewed WeChat builds without fixing their install folder."""
import hashlib
import ntpath
import os

WEIXIN_DLL_BYTES = 198060584
WEIXIN_DLL_SHA256 = '8f7406a8a465e851ee10eaecccb572d0e5b4e00d480c770938c714c396097b74'
BUILDS = (
    ('4.1.13.65', WEIXIN_DLL_BYTES, WEIXIN_DLL_SHA256),
    ('4.1.15.13', 201552944, '10f8e995453e2da46d4f2b5080cd6da1f13cc5147746adc119ceae38cb039de5'),
)


def known_binary(path, name, size, digest):
    if ntpath.basename(str(path)).casefold() != name.casefold():
        return False
    try:
        if os.stat(path).st_size != size:
            return False
        sha = hashlib.sha256()
        with open(path, 'rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                sha.update(block)
        return sha.hexdigest() == digest.casefold()
    except OSError:
        return False


def known_weixin_dll(path):
    return identify_weixin_dll(path) is not None


def identify_weixin_dll(path):
    for version, size, digest in BUILDS:
        if known_binary(path, 'Weixin.dll', size, digest):
            return version
    return None

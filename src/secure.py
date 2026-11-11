# -*- coding: utf-8 -*-
"""
导出包加解密
============
导出的数据包（作品设定 / 章节 / 正文 / 报告）默认用口令加密后再落盘或下载，
避免压缩包被转发、上传网盘或随手拷走后直接读出内容。导入时用同一口令解开。

格式（MWSEC1）：
    magic(6) | kdf_id(1) | salt(16) | nonce(12) | ciphertext | tag(16)

  · kdf_id=1：scrypt(n=2^14, r=8, p=1) 派生 32 字节密钥；
    kdf_id=2：系统 OpenSSL 不支持 scrypt 时退回 PBKDF2-HMAC-SHA256(20 万次)。
  · AES-256-GCM，附加数据（AAD）为 magic，防止头被替换。
  · 口令不落盘、不写日志；忘记口令的包无法恢复。

只依赖 pycryptodome（桌面 pip 安装，安卓端由 Chaquopy 提供 android wheel）。
"""

import hashlib
import os

MAGIC = b"MWSEC1"
KDF_SCRYPT = 1
KDF_PBKDF2 = 2
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
MIN_PASSWORD = 6


def check_password(password):
    """校验并返回去空白后的口令；不合格抛 ValueError（由 webapp 转成 400）。"""
    pwd = str(password or "").strip()
    if len(pwd) < MIN_PASSWORD:
        raise ValueError("导出口令至少 %d 位" % MIN_PASSWORD)
    if len(pwd) > 256:
        raise ValueError("口令过长（上限 256 位）")
    return pwd


def is_encrypted(blob):
    return bool(blob) and bytes(blob[:len(MAGIC)]) == MAGIC


def _derive(password, salt, kdf_id):
    raw = password.encode("utf-8") if isinstance(password, str) else password
    if kdf_id == KDF_SCRYPT:
        return hashlib.scrypt(raw, salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return hashlib.pbkdf2_hmac("sha256", raw, salt, 200000, dklen=32)


def _pick_kdf():
    try:
        hashlib.scrypt(b"x", salt=b"0" * 16, n=2 ** 14, r=8, p=1, dklen=32)
        return KDF_SCRYPT
    except (ValueError, AttributeError, OSError):
        return KDF_PBKDF2


def encrypt(data, password):
    """明文 → 加密包字节串。口令不合格抛 ValueError。"""
    from Crypto.Cipher import AES

    pwd = check_password(password)
    kdf_id = _pick_kdf()
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = _derive(pwd, salt, kdf_id)
    aes = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=TAG_LEN)
    aes.update(MAGIC)
    body, tag = aes.encrypt_and_digest(data)
    return MAGIC + bytes([kdf_id]) + salt + nonce + body + tag


def decrypt(blob, password):
    """加密包 → 明文。不是加密包 / 口令错 / 文件损坏都抛 ValueError。"""
    from Crypto.Cipher import AES

    if not is_encrypted(blob):
        raise ValueError("不是墨写加密包（缺少 MWSEC1 头）")
    rest = blob[len(MAGIC):]
    if len(rest) < 1 + SALT_LEN + NONCE_LEN + TAG_LEN:
        raise ValueError("加密包已损坏（长度不足）")
    kdf_id = rest[0]
    salt = rest[1:1 + SALT_LEN]
    nonce = rest[1 + SALT_LEN:1 + SALT_LEN + NONCE_LEN]
    body = rest[1 + SALT_LEN + NONCE_LEN:-TAG_LEN]
    tag = rest[-TAG_LEN:]
    if kdf_id not in (KDF_SCRYPT, KDF_PBKDF2):
        raise ValueError("加密包版本不支持，请升级墨写后再试")
    pwd = str(password or "").strip()
    if not pwd:
        raise ValueError("该文件已加密，请先输入导出口令")
    key = _derive(pwd, salt, kdf_id)
    aes = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=TAG_LEN)
    aes.update(MAGIC)
    try:
        return aes.decrypt_and_verify(body, tag)
    except ValueError:
        raise ValueError("口令不正确，或文件已损坏") from None

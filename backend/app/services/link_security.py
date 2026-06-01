"""SSRF-защита для серверного fetch'а по пользовательским URL (тикет z9q).

Бот скачивает страницы по ссылкам, которые присылает пользователь. Без проверки
это классический SSRF: злоумышленник присылает «ссылку» на внутренний адрес
(`127.0.0.1`, приватная сеть, `169.254.169.254` — облачная метадата) и сервер
послушно туда ходит, отдавая наружу то, что видеть нельзя.

`assert_public_url` пропускает только http/https на ПУБЛИЧНЫЕ адреса. Вызывать
ПЕРЕД каждым сетевым запросом (включая каждый редирект-хоп).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}

# CGNAT / RFC 6598 Shared Address Space — НЕ покрывается ip.is_private, но это
# внутренние адреса (ISP/k8s). Блокируем явно.
_CGNAT_RANGE = ipaddress.ip_network("100.64.0.0/10")


class UnsafeUrlError(Exception):
    """URL не прошёл SSRF-проверку (приватный адрес / запрещённая схема)."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True для любого непубличного адреса.

    Блокируем: loopback (127/8, ::1), приватные (10/8, 172.16/12, 192.168/16,
    fc00::/7), link-local (169.254/16 — облачная метадата!, fe80::/10),
    reserved, multicast, unspecified (0.0.0.0). Для IPv6-mapped IPv4
    (::ffff:10.0.0.1) проверяем встроенный IPv4.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_RANGE:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> None:
    """Бросает UnsafeUrlError, если URL небезопасен для серверного fetch'а.

    Резолвит хост и проверяет ВСЕ полученные адреса — если хоть один
    непубличный, запрос отклоняется (защита от DNS, указывающего на внутрянку).
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme not allowed: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")

    # Литеральный IP в URL — проверяем напрямую, без резолва.
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if _is_blocked_ip(literal_ip):
            raise UnsafeUrlError(f"non-public IP: {literal_ip}")
        return

    # Имя хоста — резолвим во все адреса и проверяем каждый.
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"DNS resolution failed for {host!r}: {e}") from e

    if not infos:
        raise UnsafeUrlError(f"no addresses resolved for {host!r}")

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise UnsafeUrlError(f"unparseable resolved address {ip_str!r}")
        if _is_blocked_ip(ip):
            raise UnsafeUrlError(f"{host!r} resolves to non-public IP {ip}")

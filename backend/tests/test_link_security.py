"""SSRF-guard для серверного fetch'а по URL (тикет z9q).

Критичные тесты безопасности: приватные/loopback/link-local адреса и
запрещённые схемы должны блокироваться; публичные — проходить.
"""
from __future__ import annotations

import pytest
from app.services.link_security import UnsafeUrlError, assert_public_url


class TestBlockedSchemes:
    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "data:text/html,<b>x</b>",
        "javascript:alert(1)",
    ])
    def test_non_http_schemes_blocked(self, url):
        with pytest.raises(UnsafeUrlError):
            assert_public_url(url)


class TestBlockedLiteralIPs:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/admin",
        "http://127.0.0.1:8080/",
        "https://localhost/",          # резолвится в loopback
        "http://0.0.0.0/",
        "http://10.0.0.5/internal",
        "http://172.16.10.1/",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",  # облачная метадата!
        "http://[::1]/",               # IPv6 loopback
        "http://100.64.0.1/",          # CGNAT / RFC 6598 (внутренний у ISP/k8s)
        "http://100.127.255.254/",     # верхняя граница CGNAT
    ])
    def test_private_and_loopback_blocked(self, url):
        with pytest.raises(UnsafeUrlError):
            assert_public_url(url)

    def test_ipv6_mapped_ipv4_private_blocked(self):
        # ::ffff:10.0.0.1 — IPv4-mapped приватный адрес
        with pytest.raises(UnsafeUrlError):
            assert_public_url("http://[::ffff:10.0.0.1]/")


class TestMalformed:
    def test_no_host_blocked(self):
        with pytest.raises(UnsafeUrlError):
            assert_public_url("http:///path-only")

    def test_unresolvable_host_blocked(self):
        with pytest.raises(UnsafeUrlError):
            assert_public_url("http://nonexistent.invalid-tld-zzz./")


class TestPublicAllowed:
    def test_public_ip_literal_passes(self):
        # 1.1.1.1 — публичный (Cloudflare), без DNS
        assert_public_url("https://1.1.1.1/")  # не бросает

    def test_public_host_passes(self, monkeypatch):
        # Мокаем DNS, чтобы не зависеть от сети: публичный адрес → проходит.
        def fake_getaddrinfo(host, *a, **k):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]  # example.com public
        monkeypatch.setattr(
            "app.services.link_security.socket.getaddrinfo", fake_getaddrinfo
        )
        assert_public_url("https://example.com/article")  # не бросает

    def test_host_resolving_to_private_blocked(self, monkeypatch):
        # DNS-rebinding защита: имя резолвится во внутренний адрес → блок.
        def fake_getaddrinfo(host, *a, **k):
            return [(2, 1, 6, "", ("10.1.2.3", 0))]
        monkeypatch.setattr(
            "app.services.link_security.socket.getaddrinfo", fake_getaddrinfo
        )
        with pytest.raises(UnsafeUrlError):
            assert_public_url("https://evil.example.com/")

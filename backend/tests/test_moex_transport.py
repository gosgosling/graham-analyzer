"""MOEX должен использовать EXTRA_CA_CERTS так же, как T-Invest."""
from app.utils import http_session, moex_client


def test_moex_uses_configured_ca_without_environment_proxy(monkeypatch):
    calls = []
    monkeypatch.setattr(moex_client, '_moex_session', None)
    monkeypatch.setattr(http_session, 'ca_bundle', lambda: '/configured/extra-ca-bundle.pem')
    monkeypatch.setenv('HTTPS_PROXY', 'http://unreachable-proxy.invalid:9999')

    def get(session, url, **kwargs):
        calls.append((session, url, kwargs))
        assert session.trust_env is False
        assert session.verify == '/configured/extra-ca-bundle.pem'
        return 'response'

    monkeypatch.setattr(http_session.requests.Session, 'get', get)
    assert moex_client._moex_get('https://iss.moex.com/test', params={'iss.meta': 'off'}) == 'response'
    assert moex_client._moex_get('https://iss.moex.com/test', timeout=10) == 'response'
    assert calls[0][0] is calls[1][0]
    assert calls[0][2] == {'timeout': 15, 'params': {'iss.meta': 'off'}}
    assert calls[1][2] == {'timeout': 10}

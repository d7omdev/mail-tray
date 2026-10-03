import threading
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
import requests

from mailtray import __main__ as cli, auth, setup_service, storage
from mailtray.setup_web import make_server


@pytest.fixture
def wizard(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    server = make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    yield server, base
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def post(base, server, path, data, headers=None):
    return requests.post(base + path, data=data, timeout=5, headers={
        'X-Setup-Token': server.state.csrf,
        'Content-Type': 'application/x-www-form-urlencoded', **(headers or {})
    })


def test_setup_page_shows_exact_links_and_existing_status(wizard):
    server, base = wizard
    page = requests.get(base, timeout=5)
    assert page.status_code == 200
    assert 'console.cloud.google.com/apis/library/gmail.googleapis.com' in page.text
    assert 'console.cloud.google.com/auth/audience' in page.text
    assert 'console.cloud.google.com/auth/clients' in page.text
    assert 'http://127.0.0.1:8765/callback' in page.text
    assert 'X-Setup-Token' in page.text
    assert 'no-store' == page.headers['Cache-Control']
    assert 'frame-ancestors' in page.headers['Content-Security-Policy']
    assert requests.get(base + '/status', timeout=5).json()['accounts'] == []
    for name in ('gmail', 'zoho'):
        assert requests.get(base + f'/icons/{name}.png', timeout=5).headers['Content-Type'] == 'image/png'


def test_setup_rejects_cross_origin_missing_csrf_and_invalid_input(wizard):
    server, base = wizard
    form = {'provider': 'gmail', 'region': 'com', 'client_id': 'desktop-id'}
    assert requests.post(base + '/connect', data=form, timeout=5).status_code == 403
    assert post(base, server, '/connect', form, {'Origin': 'https://evil.example'}).status_code == 403
    assert requests.get(base, headers={'Host': 'evil.example'}, timeout=5).status_code == 403
    assert post(base, server, '/connect', {**form, 'provider': 'bad'}).status_code == 400
    assert post(base, server, '/connect', {**form, 'client_id': ''}).status_code == 400
    assert post(base, server, '/connect', {**form, 'client_id': 'x' * 5000}).status_code == 400
    assert server.state.snapshot()['stage'] == 'ready'


def test_browser_setup_succeeds_without_exposing_credentials(wizard):
    server, base = wizard
    secret = 'private-client-secret'
    def connect(provider, client_id, client_secret, region, select):
        assert (provider, client_id, client_secret, region) == ('gmail', 'my-id', secret, 'com')
        storage.save(storage.config_dir() / 'accounts.json', {'accounts': [
            {'id': 'gmail:google:me@example.com', 'provider': 'gmail', 'email': 'me@example.com'}
        ]})
        return {'email': 'me@example.com'}
    with patch('mailtray.setup_web.connect_account', side_effect=connect):
        response = post(base, server, '/connect', {'provider': 'gmail', 'client_id': 'my-id',
                                                   'client_secret': secret, 'region': 'com'})
        assert response.status_code == 202
        for _ in range(100):
            status = requests.get(base + '/status', timeout=5).json()
            if status['stage'] == 'connected':
                break
            time.sleep(.01)
        assert status['stage'] == 'connected'
        assert status['accounts'] == [{'provider': 'gmail', 'email': 'me@example.com'}]
        assert 'within a minute' in status['message']
        assert secret not in response.text + str(status) + requests.get(base, timeout=5).text
    assert post(base, server, '/close', {}).status_code == 200


def test_setup_reports_provider_error_without_claiming_success(wizard):
    server, base = wizard
    with patch('mailtray.setup_web.connect_account', side_effect=RuntimeError(
            'Gmail refused access (403). Enable the Gmail API.')):
        assert post(base, server, '/connect', {'provider': 'gmail', 'client_id': 'id',
               'client_secret': '', 'region': 'com'}).status_code == 202
        for _ in range(100):
            status = requests.get(base + '/status', timeout=5).json()
            if status['stage'] == 'error':
                break
            time.sleep(.01)
        assert status['stage'] == 'error'
        assert 'Enable the Gmail API' in status['message']
        assert status['accounts'] == []


def test_zoho_multiple_mailboxes_requires_valid_selection(wizard):
    server, base = wizard
    def connect(provider, client_id, client_secret, region, select):
        selected = select([{'primaryEmailAddress': 'first@example.com'},
                           {'primaryEmailAddress': 'second@example.com'}])
        assert selected == 1
        return {'email': 'second@example.com'}
    with patch('mailtray.setup_web.connect_account', side_effect=connect):
        assert post(base, server, '/connect', {'provider': 'zoho', 'client_id': 'id',
               'client_secret': 'secret', 'region': 'eu'}).status_code == 202
        for _ in range(100):
            status = requests.get(base + '/status', timeout=5).json()
            if status['stage'] == 'choosing':
                break
            time.sleep(.01)
        assert status['mailboxes'] == ['first@example.com', 'second@example.com']
        assert post(base, server, '/select', {'index': '2'}).status_code == 400
        assert post(base, server, '/close', {}).status_code == 409
        assert post(base, server, '/select', {'index': '1'}).status_code == 200
        for _ in range(100):
            if server.state.snapshot()['stage'] == 'connected':
                break
            time.sleep(.01)
        assert server.state.snapshot()['stage'] == 'connected'


def test_guided_setup_oauth_callback_to_final_account_status(wizard):
    server, base = wizard
    callback_page = []

    def open_browser(url):
        params = parse_qs(urlsplit(url).query)
        redirect = params['redirect_uri'][0]
        def callback():
            response = requests.get(redirect, params={'state': params['state'][0], 'code': 'mock-code'}, timeout=5)
            callback_page.append(response.text)
        threading.Thread(target=callback, daemon=True).start()
        return True

    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {'access_token': 'private-access', 'refresh_token': 'private-refresh', 'expires_in': 3600}

    real_post = requests.post
    def fake_post(url, *args, **kwargs):
        return Response() if url == auth.GOOGLE_TOKEN else real_post(url, *args, **kwargs)

    with patch.object(auth.webbrowser, 'open', side_effect=open_browser), \
         patch.object(auth.requests, 'post', side_effect=fake_post), \
         patch.object(setup_service, 'get', return_value={'emailAddress': 'user@example.com'}), \
         patch.object(setup_service, 'secret_set') as secret_set:
        assert post(base, server, '/connect', {'provider': 'gmail', 'region': 'com',
               'client_id': 'desktop-id', 'client_secret': 'secret'}).status_code == 202
        for _ in range(100):
            status = requests.get(base + '/status', timeout=5).json()
            if status['stage'] == 'connected':
                break
            time.sleep(.01)
        assert status['stage'] == 'connected'
        assert status['accounts'] == [{'email': 'user@example.com', 'provider': 'gmail'}]
        assert callback_page and 'Return to Mail Tray setup' in callback_page[0]
        assert 'private-access' not in str(status)
        secret_set.assert_called_once()


def test_gmail_profile_denied_is_not_mistaken_for_connected(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    response = requests.Response()
    response.status_code = 403
    error = requests.HTTPError(response=response)
    with patch.object(setup_service, 'authorize', return_value={'access_token': 'private'}), \
         patch.object(setup_service, 'get', side_effect=error), \
         patch.object(setup_service, 'secret_set') as secret_set:
        with pytest.raises(RuntimeError, match='Enable the Gmail API'):
            setup_service.connect_account('gmail', 'id', 'secret')
    secret_set.assert_not_called()
    assert storage.accounts() == []


def test_terminal_setup_remains_available(monkeypatch):
    monkeypatch.setattr('sys.argv', ['mail-tray', 'setup', 'gmail'])
    with patch('builtins.input', return_value='desktop-id'), \
         patch.object(cli.getpass, 'getpass', return_value=''), \
         patch.object(cli, 'connect_account', return_value={'email': 'user@example.com'}) as connect:
        cli.main()
    connect.assert_called_once()
    assert connect.call_args.args[:4] == ('gmail', 'desktop-id', '', 'com')


def test_terminal_and_browser_share_validation_and_storage(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    credentials = {'access_token': 'private-token', 'refresh_token': 'private-refresh'}
    with patch.object(setup_service, 'authorize', return_value=credentials), \
         patch.object(setup_service, 'get', return_value={'emailAddress': 'me@example.com'}), \
         patch.object(setup_service, 'secret_set') as save_secret:
        account = setup_service.connect_account('gmail', ' id ', ' secret ')
    assert account['email'] == 'me@example.com'
    assert storage.accounts() == [account]
    save_secret.assert_called_once_with(account['id'], credentials)
    assert 'private-token' not in (tmp_path / 'mail-tray' / 'accounts.json').read_text()
    with pytest.raises(ValueError):
        setup_service.connect_account('zoho', 'id', '', 'com')

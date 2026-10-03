import time
from unittest.mock import patch

from mailtray import auth, storage


def test_storage_writes_private_nonsecret_config(tmp_path):
    path = tmp_path / 'nested' / 'accounts.json'
    storage.save(path, {'accounts': [{'email': 'me@example.com'}]})
    assert storage.load(path, {})['accounts'][0]['email'] == 'me@example.com'
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_file_uses_default(tmp_path):
    assert storage.load(tmp_path / 'notfound', {'accounts': []}) == {'accounts': []}


def test_refresh_uses_keyring_and_persists_new_access_token():
    data = {'client_id': 'id', 'client_secret': 'secret', 'refresh_token': 'refresh',
            'access_token': 'expired', 'expires_at': 0}
    captured = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'access_token': 'new', 'expires_in': 3600}
    with patch.object(auth, 'secret_get', return_value=data), \
         patch.object(auth, 'secret_set', side_effect=lambda account, value: captured.append((account, value.copy()))), \
         patch.object(auth.requests, 'post', return_value=Response()) as post:
        assert auth.token_for({'id': 'gmail:google:test', 'provider': 'gmail'}) == 'new'
    assert post.call_args.kwargs['data']['refresh_token'] == 'refresh'
    assert captured[0][1]['access_token'] == 'new'
    assert captured[0][1]['expires_at'] > time.time()


def test_valid_access_token_does_not_refresh():
    with patch.object(auth, 'secret_get', return_value={'access_token': 'valid',
         'expires_at': time.time() + 3600}):
        with patch.object(auth.requests, 'post') as post:
            assert auth.token_for({'id': 'id', 'provider': 'zoho', 'region': 'eu'}) == 'valid'
            post.assert_not_called()

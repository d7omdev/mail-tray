from unittest.mock import patch

from mailtray import providers


def test_account_inbox_urls_are_provider_specific():
    assert providers.inbox_url({'provider': 'gmail', 'email': 'a+b@example.com'}) == (
        'https://mail.google.com/mail/u/?authuser=a%2Bb%40example.com#inbox'
    )
    assert providers.inbox_url({'provider': 'zoho', 'region': 'eu'}) == (
        'https://mail.zoho.eu/zm/#mail/folder/inbox'
    )


def test_gmail_reads_headers_unread_label_and_thread_url():
    def fake_get(url, token, provider, **params):
        if url.endswith('/messages'):
            assert params['labelIds'] == 'INBOX'
            return {'messages': [{'id': 'a'}]}
        if url.endswith('/labels/INBOX'):
            return {'messagesUnread': 12}
        return {'threadId': 'thread1', 'labelIds': ['INBOX', 'UNREAD'],
                'payload': {'headers': [{'name': 'From', 'value': 'Alice'},
                                        {'name': 'Subject', 'value': 'Hello'}]}}

    with patch.object(providers, 'get', side_effect=fake_get):
        messages, unread = providers.gmail_mail({'email': 'me@gmail.com'}, 'token')
    assert unread == 12
    assert messages[0].sender == 'Alice'
    assert messages[0].unread
    assert '#all/thread1' in messages[0].url


def test_zoho_uses_inbox_and_counts_unread_separately():
    def fake_get(url, token, provider, **params):
        if url.endswith('/folders'):
            return {'data': [{'folderType': 'Inbox', 'path': '/Inbox', 'folderId': '42'}]}
        assert params['folderId'] == '42'
        if params.get('status') == 'unread':
            return {'data': [{'messageId': '5'}]}
        return {'data': [{'messageId': '5', 'fromAddress': 'A &amp; B',
                          'subject': 'Hi &amp; bye', 'status': '0'}]}

    account = {'region': 'eu', 'account_id': '123'}
    with patch.object(providers, 'get', side_effect=fake_get):
        messages, unread = providers.zoho_mail(account, 'token')
    assert unread == 1
    assert messages[0].sender == 'A & B'
    assert messages[0].subject == 'Hi & bye'
    assert messages[0].unread


def test_failed_zoho_status_is_not_silently_accepted():
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'status': {'code': 401}}
    with patch.object(providers.requests, 'get', return_value=Response()):
        try:
            providers.get('https://mail.zoho.eu/api/accounts', 'token', 'zoho')
        except RuntimeError:
            pass
        else:
            assert False, 'Expected API error'

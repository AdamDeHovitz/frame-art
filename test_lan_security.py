"""Password-free LAN sharing boundaries; never commands a real TV."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch

from lan_security import normalize_origin
import server as app


class QuietHandler(app.Handler):
    def log_message(self, *args):
        pass


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        cls.server.lan_origin = 'http://192.168.1.20:8000'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        supplied = {'Host': '192.168.1.20:8000'}
        if method == 'POST':
            supplied.update({'Origin': self.server.lan_origin, 'X-Stillroom-Request': '1', 'Content-Type': 'application/json'})
        supplied.update(headers or {})
        connection.request(method, path, body=body, headers=supplied)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_no_login_required(self):
        for path in ('/', '/app.js', '/network.js', '/styles.css', '/fonts/dm-sans.ttf', '/api/collections'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 200)
        self.assertIsInstance(json.loads(self.request('/api/collections')[1])['collections'], list)
        self.assertEqual(self.request('/login')[0], 404)

    def test_private_files_get_and_head(self):
        for path in ('/server.py', '/.git/config', '/work/tv/', '/outputs/', '/collections.json',
                     '/%2e%2e/server.py', '/app.js/../server.py'):
            for method in ('GET', 'HEAD'):
                with self.subTest(path=path, method=method):
                    status, body = self.request(path, method)
                    self.assertEqual(status, 404)
                    if method == 'HEAD':
                        self.assertEqual(body, b'')
        self.assertEqual(self.request('/', 'HEAD'), (200, b''))

    def test_host_and_cross_site_checks(self):
        for headers in ({'Host':'attacker.example'}, {'Origin':'http://attacker.example'},
                        {'Sec-Fetch-Site':'cross-site'}, {'Sec-Fetch-Site':'same-site'}):
            self.assertEqual(self.request('/api/collections', headers=headers)[0], 403)

    def test_tv_post_requires_app_headers(self):
        with patch('server.stop_slideshow', return_value={'running':False}) as stop:
            for headers in ({'Origin':''}, {'Origin':'http://attacker.example'}, {'X-Stillroom-Request':''}):
                self.assertEqual(self.request('/api/tv/slideshow/stop', 'POST', '{}', headers)[0], 403)
            stop.assert_not_called()
            self.assertEqual(self.request('/api/tv/slideshow/stop', 'POST', '{}')[0], 200)
            stop.assert_called_once()

    def test_duplicate_host_rejected(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.putrequest('GET', '/', skip_host=True)
        connection.putheader('Host', '192.168.1.20:8000')
        connection.putheader('Host', 'attacker.example')
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.close()


class ConfigTests(unittest.TestCase):
    def test_private_addresses(self):
        for address in ('192.168.1.20', '10.0.0.2', '172.16.1.2', '127.0.0.1'):
            self.assertEqual(normalize_origin(f'http://{address}:8000/'), f'http://{address}:8000')

    def test_unsafe_addresses(self):
        for origin in ('http://8.8.8.8', 'http://0.0.0.0', 'http://169.254.1.1', 'http://example.com',
                       'http://192.168.1.20/path', 'http://user@192.168.1.20', 'http://192.168.1.20:0'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                normalize_origin(origin)

    def test_default_localhost_unchanged(self):
        with patch('sys.argv', ['server.py']), patch('server.ThreadingHTTPServer') as constructor, patch('builtins.print'):
            constructor.return_value.serve_forever.side_effect = KeyboardInterrupt
            app.main()
            self.assertEqual(constructor.call_args.args[0], ('127.0.0.1', 8000))
            self.assertIsNone(constructor.return_value.lan_origin)

    def test_lan_binds_only_selected_interface_without_password(self):
        with patch('sys.argv', ['server.py', '--lan', '--bind', '192.168.1.20', '--port', '8001']), patch('server.ThreadingHTTPServer') as constructor, patch('builtins.print'):
            constructor.return_value.serve_forever.side_effect = KeyboardInterrupt
            app.main()
            self.assertEqual(constructor.call_args.args[0], ('192.168.1.20', 8001))
            self.assertEqual(constructor.return_value.lan_origin, 'http://192.168.1.20:8001')

    def test_requires_explicit_lan_configuration(self):
        for args in (['--lan'], ['--bind','192.168.1.20'], ['--lan','--bind','8.8.8.8']):
            with patch('sys.argv', ['server.py', *args]), patch('sys.stderr'), self.assertRaises(SystemExit):
                app.main()


if __name__ == '__main__':
    unittest.main()

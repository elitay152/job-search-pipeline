"""Import a single user-supplied public job URL. No crawling, login or browser automation."""
import ipaddress
import json
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import httpx

MAX_BYTES = 1_000_000


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Use a public HTTPS posting link without login information.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError('Private and local network addresses are not supported.')
    except socket.gaierror as exc:
        raise ValueError('Could not find this website. Paste the job description instead.') from exc
    return url


class JobHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []
        self.scripts = []
        self.script = None
        self.hidden = {'script', 'style', 'nav', 'header', 'footer', 'noscript', 'svg'}

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type', '').lower() == 'application/ld+json':
            self.script = []
        if tag in self.hidden:
            self.skip += 1
        if not self.skip and tag in ('p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'section'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        if tag in self.hidden:
            self.skip = max(0, self.skip - 1)
        if not self.skip and tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'section'):
            self.parts.append('\n')

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        if not self.skip:
            self.parts.append(data)


def posting_nodes(node):
    if isinstance(node, list):
        for value in node:
            yield from posting_nodes(value)
    elif isinstance(node, dict):
        types = node.get('@type', [])
        if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
            yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from posting_nodes(value)


def readable(html):
    parser = JobHTML()
    parser.feed(html)
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip())


def extract_posting(html):
    parser = JobHTML()
    parser.feed(html)
    for raw in parser.scripts:
        try:
            for node in posting_nodes(json.loads(raw)):
                if node.get('description'):
                    return str(node.get('title', '')) + '\n' + readable(unescape(str(node['description'])))
        except (ValueError, TypeError):
            continue
    return readable(html)


def load_job_url(url, client=None):
    owned = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=False)
    try:
        for _ in range(4):
            public_url(url)
            with client.stream('GET', url, headers={'User-Agent': 'ApplicationStudio/0.1 (user-requested job import)'}, follow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('location')
                    if not location:
                        raise ValueError('This posting redirected without a destination. Paste its text instead.')
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get('content-type', '').lower()
                if not any(t in content_type for t in ('text/html', 'text/plain')):
                    raise ValueError('This link is not a readable job page. Paste its description instead.')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ValueError('This page is too large. Paste just the job description instead.')
                content = body.decode('utf-8', errors='replace')
                text = extract_posting(content) if 'html' in content_type else content
                if not 20 <= len(text.strip()) <= 50000:
                    raise ValueError('Could not extract a usable job description. Paste its text instead.')
                return text
        raise ValueError('Too many redirects. Paste the job description instead.')
    except httpx.HTTPError as exc:
        raise ValueError('This website blocked access or could not be reached. Paste the job description instead; no login bypass is attempted.') from exc
    finally:
        if owned:
            client.close()

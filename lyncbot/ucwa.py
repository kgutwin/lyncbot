
import re
import json
import uuid
import urllib
import urllib2
import urlparse

### TERRIBLE MONKEY PATCH TO AVOID SSL CERT ISSUE
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
###

class UCWAResource(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, args[0])
        self._ucwa = kwargs['ucwa']
        
        for link in self.get('_links', {}):
            if link == 'self':
                continue
            def link_closure(href=self['_links'][link]['href'], POST=None,
                             **kwargs):
                if kwargs:
                    href += "?" + urllib.urlencode(kwargs)
                return self._get_url(href, POST)
            link_closure.__name__ = str(link)
            setattr(self, link, link_closure)

        for embed in self.get('_embedded', {}):
            value = self['_embedded'][embed]
            if isinstance(value, list):
                setattr(self, embed, [UCWAResource(r, ucwa=self._ucwa)
                                      for r in value])
            else:
                setattr(self, embed, UCWAResource(value, ucwa=self._ucwa))

    def _get_url(self, url, data):
        url = self._ucwa.appbase + url
        req = urllib2.urlopen(self._ucwa._request(url, data))
        try:
            res = UCWAResource(json.load(req), ucwa=self._ucwa)
        except ValueError:
            return None
        
        if hasattr(res, 'next'):
            return UCWAIterator(res)
        else:
            return res

    def refresh(self):
        ucwa = self._ucwa
        url = ucwa.appbase + self['_links']['self']['href']
        req = urllib2.urlopen(ucwa._request(url))
        j = json.load(req)
        self.clear()
        self.__init__(j, ucwa=ucwa)
        

class UCWAIterator:
    def __init__(self, initial):
        self.initial = initial

    def __iter__(self):
        cur = self.initial
        yield self.initial
        while hasattr(cur, 'next'):
            cur = cur.next()
            yield cur
        

class LyncUCWA:
    def __init__(self, username, password):
        self.auth_headers = None

        # Look up discovery URL and user URL
        domain = username[username.find('@')+1:]
        discover_url = "https://lyncdiscover.%s/" % domain
        discover_json = json.load(urllib2.urlopen(discover_url))
        self.user_url = discover_json['_links']['user']['href']

        self.login(username, password)

    def _request(self, url, data=None, mode='json'):
        headers = self.auth_headers.copy()
        if data is not None:
            if mode == 'json':
                data = json.dumps(data)
                headers['Content-Type'] = 'application/json'
                headers['Content-Length'] = len(data)
            elif mode == 'urlenc':
                data = urllib.urlencode(data)
        return urllib2.Request(url, data, headers=self.auth_headers)
        
    def login(self, username, password):
        # Ping the user URL, expecting a 401 and address of oauth server
        try:
            user_response = urllib2.urlopen(self.user_url)
        except urllib2.HTTPError, error_response:
            wwwauth_header = error_response.info()['www-authenticate']
        auth_url_re = re.search('MsRtcOAuth href="([^"]*)"', wwwauth_header)
        auth_url = auth_url_re.group(1)

        # verify domain
        user_url_parse = urlparse.urlparse(self.user_url)
        auth_url_parse = urlparse.urlparse(auth_url)
        if user_url_parse[1] != auth_url_parse[1]:
            self.user_url = urlparse.urlunparse(
                [user_url_parse[0], auth_url_parse[1]] + list(user_url_parse[2:])
                )
            self.login(username, password)

        # Send auth request
        auth_data = {
            'grant_type': 'password',
            'username': username,
            'password': password
            }
        auth_request = urllib2.urlopen(auth_url,
                                       data=urllib.urlencode(auth_data))
        access_token = json.load(auth_request)

        # Resend user request with oauth headers, get applications url
        self.auth_headers = {
            'Authorization':" ".join((access_token['token_type'],
                                      access_token['access_token'])),
            'Content-Type': 'application/json'
            }
        app_request = urllib2.urlopen(self._request(self.user_url))
        app_url = json.load(app_request)['_links']['applications']['href']
        app_data = {
            'culture': 'en-US',
            'endpointId': str(uuid.uuid1()),
            'userAgent': 'fooApp/1.0 (Linux)'
            }

        # verify domain again
        app_url_parse = urlparse.urlparse(app_url)
        if user_url_parse[1] != app_url_parse[1]:
            self.user_url = urlparse.urlunparse(
                [user_url_parse[0], app_url_parse[1]] + list(user_url_parse[2:])
                )
            self.login(username, password)

        self.application_json = json.load(urllib2.urlopen(
            self._request(app_url, app_data)))
        self.appbase = urlparse.urlunparse(
            urlparse.urlparse(app_url)[:2] + ('',) * 4)
        self.application = UCWAResource(self.application_json, ucwa=self)
        
    def search(self, query):
        return self.application.people.search(query=query)

    def set_available(self, avail=True):
        request_body = {
            'signInAs': 'Online' if avail else 'Away',
            'supportedMessageFormats': ['Plain', 'Html'],
            'supportedModalities': ['Messaging'] if avail else []
        }
        return self.application.me.makeMeAvailable(POST=request_body)

    def listen(self):
        """Listen for UCWA events."""
        return self.application.events()
        
    
if __name__ == "__main__":
    import getpass
    username = raw_input("Username (email): ")
    password = getpass.getpass()

    http_logger = urllib2.HTTPHandler(debuglevel=1)
    opener = urllib2.build_opener(http_logger)
    urllib2.install_opener(opener)

    try:
        l = LyncUCWA(username, password)
        c = l.search(username)
        #c = l.search('Rajesh')
        for contact in c.contact:
            print contact.contactPresence()

        # set available and listen for events
        l.set_available()
        for event in l.listen():
            print json.dumps(event, indent=2)
            # TODO: at this point the UCWAResource object has no
            # specific support for events

    except urllib2.HTTPError, e:
        print e
        print e.read()
        

from __future__ import print_function

import re
import json
import uuid
import base64
import codecs

try:
    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen, Request
    from urllib.parse import urlparse, urlunparse, urlencode
except ImportError:
    # for temporary py2/3 compatibility
    from urllib import urlencode
    from urllib2 import HTTPError, URLError, urlopen, Request
    from urlparse import urlparse, urlunparse
    input = raw_input

utfr = codecs.getreader('utf-8')

### TERRIBLE MONKEY PATCH TO AVOID SSL CERT ISSUE
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
###

# Things to do:
# 2. Build an events system
#    - refactor LyncUCWA.listen() to a process_events() call that:
#      - takes each emitted event
#      - walks down the self.application tree and updates the local data model
#      - invokes any callbacks registered to individual elements of the model
# 3. Build a callback system

class UCWAResource(dict):
    # some links or properties map to Python reserved words; these are
    # synonyms.
    RESERVED_ALT = {
        'from': 'frm'
    }
    RESERVED_ALT_REV = dict(zip(RESERVED_ALT.values(), RESERVED_ALT.keys()))

    def __init__(self, *args, **kwargs):
        dict.__init__(self)
        self._ucwa = kwargs['ucwa']
        if 'href' in kwargs:
            self.update({'_links': {'self': {'href': kwargs['href']}}})
        else:
            self.update(args[0])
        
    def update(self, other):
        dict.update(self, other)
        for link in self.get('_links', {}):
            if link == 'self':
                continue
            href = self['_links'][link]['href']
            new_attr = None
            if href.startswith('/'):
                new_attr = UCWAResource(href=href, ucwa=self._ucwa)
            elif href.startswith('data:'):
                # TODO: decode data here
                new_attr = href
            if new_attr is not None:
                setattr(self, link, new_attr)
                if link in self.RESERVED_ALT:
                    setattr(self, self.RESERVED_ALT[link], new_attr)
                
        for embed in self.get('_embedded', {}):
            value = self['_embedded'][embed]
            if isinstance(value, list):
                setattr(self, embed, [UCWAResource(r, ucwa=self._ucwa)
                                      for r in value])
            else:
                setattr(self, embed, UCWAResource(value, ucwa=self._ucwa))

    def __getattr__(self, name):
        if (list(self.keys()) == ['_links'] and
            list(self['_links'].keys()) == ['self']):
            # we're a stub, refresh before proceeding
            self.refresh()
        if name in self:
            return self[name]
        elif name in self.RESERVED_ALT_REV:
            return self[self.RESERVED_ALT_REV[name]]
        else:
            return self.__getattribute__(name)
                
    def __call__(self, POST=None, **kwargs):
        return self._get_url(self['_links']['self']['href'], POST=POST,
                             **kwargs)
    
    def _get_url(self, url, POST=None, **kwargs):
        url = self._ucwa.appbase + url
        if kwargs:
            url += "?" + urlencode(kwargs)

        mode = 'json'
        if POST is True:
            POST = ''
            mode = 'raw'
        elif isinstance(POST, str):
            mode = 'plain'
        req = urlopen(self._ucwa._request(url, POST, mode))
        
        if req.getheader('Content-Type') == 'application/json':
            res = UCWAResource(json.load(utfr(req)), ucwa=self._ucwa)
            if hasattr(res, 'next'):
                return UCWAIterator(res)
            else:
                return res
        elif req.getheader('Location'):
            return req.getheader('Location')

    def refresh(self):
        ucwa = self._ucwa
        url = ucwa.appbase + self['_links']['self']['href']
        req = urlopen(ucwa._request(url))
        j = json.load(utfr(req))
        self.clear()
        self.__init__(j, ucwa=ucwa)


class UCWAIterator:
    def __init__(self, initial):
        self.initial = initial

    def __iter__(self):
        cur = self.initial
        yield self.initial
        while hasattr(cur, 'next'):
            cur = cur.next
            cur.refresh()
            yield cur
        

class UCWAConversation:
    def __init__(self, ucwa, other):
        self.ucwa = ucwa
        self.other = other
        self.conversation = None
        self.inbound_callback = None
        self.invite_message = None

    def send(self, message):
        if self.conversation is not None:
            self.conversation.messaging.sendMessage(POST=message)
        else:
            msg_b64 = base64.b64encode(message)
            loc = ucwa.application.communication.startMessaging(POST={
                "to": "sip:" + self.other[0],
                "_links": {
                    "message": {
                        "href": "data:text/plain;base64,%s" % msg_b64
                    }
                }
            })
            if not loc:
                raise Exception("failed to send messagingInvitation")
            invite = UCWAResource(href=loc, ucwa=self.ucwa)
            self.conversation = invite.conversation
            # TODO: if len(other) > 1, invite others
            self.ucwa.register_callback(self._inbound_message, 'conversation',
                                        link_rel='message')

    def set_inbound_callback(self, cb):
        self.inbound_callback = cb

    def _inbound_message(self, u, event):
        sender = event.message.contact.name.split()[0]
        message = "%s: %s" % (sender, event.message.plainMessage)
        self.inbound_callback(message)


class LyncUCWA:
    def __init__(self, username, password):
        self.auth_headers = None
        self.callbacks = {}
        
        # Look up discovery URL and user URL
        domain = username[username.find('@')+1:]
        discover_url = "https://lyncdiscover.%s/" % domain
        try:
            discover_json = json.load(utfr(urlopen(discover_url)))
        except URLError:
            raise Exception("could not contact discovery url %s" %
                            discover_url)
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
                data = urlencode(data)
            elif mode == 'html':
                headers['Content-Type'] = 'text/html'
                headers['Content-Length'] = len(data)
            elif mode == 'plain':
                headers['Content-Type'] = 'text/plain'
                headers['Content-Length'] = len(data)
            data = bytes(data, 'utf-8')
        return Request(url, data, headers=self.auth_headers)
        
    def login(self, username, password):
        # Ping the user URL, expecting a 401 and address of oauth server
        try:
            user_response = urlopen(self.user_url)
        except HTTPError as error_response:
            wwwauth_header = str(error_response.info())
        auth_url_re = re.search('MsRtcOAuth href="([^"]*)"', wwwauth_header)
        try:
            auth_url = auth_url_re.group(1)
        except AttributeError:
            raise AttributeError("missing auth_url in %s" % repr(wwwauth_header))

        # verify domain
        user_url_parse = urlparse(self.user_url)
        auth_url_parse = urlparse(auth_url)
        if user_url_parse[1] != auth_url_parse[1]:
            self.user_url = urlunparse(
                [user_url_parse[0], auth_url_parse[1]] + list(user_url_parse[2:])
                )
            self.login(username, password)

        # Send auth request
        auth_data = {
            'grant_type': 'password',
            'username': username,
            'password': password
            }
        auth_request = urlopen(auth_url, data=bytes(urlencode(auth_data),
                                                    'utf-8'))
        access_token = json.load(utfr(auth_request))

        # Resend user request with oauth headers, get applications url
        self.auth_headers = {
            'Authorization':" ".join((access_token['token_type'],
                                      access_token['access_token'])),
            'Content-Type': 'application/json'
            }
        app_request = urlopen(self._request(self.user_url))
        app_url = json.load(utfr(app_request))['_links']['applications']['href']
        app_data = {
            'culture': 'en-US',
            'endpointId': str(uuid.uuid1()),
            'userAgent': 'lyncbotApp/1.0 (Linux)'
            }

        # verify domain again
        app_url_parse = urlparse(app_url)
        if user_url_parse[1] != app_url_parse[1]:
            self.user_url = urlunparse(
                [user_url_parse[0], app_url_parse[1]] + list(user_url_parse[2:])
                )
            self.login(username, password)

        self.application_json = json.load(utfr(urlopen(
            self._request(app_url, app_data))))
        self.appbase = urlunparse(
            urlparse(app_url)[:2] + ('',) * 4)
        self.application = UCWAResource(self.application_json, ucwa=self)
        
    def search(self, query):
        return self.application.people.search(query=query).contact

    def contacts(self, query=None):
        # TODO: add groups support?
        all_contacts = self.application.people.myContacts.contact
        if query is not None:
            if '@' in query:
                return [c for c in all_contacts if query in c.emailAddresses]
            else:
                return [c for c in all_contacts
                        if c.name.lower().startswith(query.lower())]
        else:
            return all_contacts
    
    def set_available(self, avail=True):
        request_body = {
            'signInAs': 'Online' if avail else 'Away',
            'supportedMessageFormats': ['Plain', 'Html'],
            'supportedModalities': ['Messaging'] if avail else []
        }
        return self.application.me.makeMeAvailable(POST=request_body)

    def _parse_href(self, href):
        hbase = urlparse(self.appbase).path
        assert href.startswith(hbase)
        if href == hbase:
            return []
        return href[len(hbase)+1:].split('/')

    def normalize_contact(self, name):
        if isinstance(name, list):
            name = " ".join(name)
        # TODO: check if name matches email regex, if so, return directly
        hits = self.contacts(name)
        if not hits:
            hits = list(self.search(name))
        if not hits:
            raise Exception("couldn't find %s" % name)
        hits = [h.email for h in hits]
        if len(hits) != 1:
            raise Exception("the name %s was ambiguous - found %s" %
                            (name, ", ".join(hits)))
        return hits[0]

    def new_conversation(self, other):
        return UCWAConversation(self, other)

    def set_invitation_callback(self, cb):
        def invite_callback(u, event):
            other = getattr(event.messagingInvitation, 'from')\
                .uri.split(':')[1]
            event.accept(POST=True)
            conversation = UCWAConversation(u, other)
            conversation.conversation = event.conversation
            conversation.invite_message = event.messagingInvitation.message
            cb(conversation)

        self.register_callback(invite_callback, 'communication',
                               link_rel='messagingInvitation',
                               ev_type='started')

    def register_callback(self, callback, rel, link_rel=None, ev_type=None):
        rel = [rel]
        if link_rel is not None:
            rel.append(link_rel)
            if ev_type is not None:
                rel.append(ev_type)
        rel = tuple(rel)
        self.callbacks.setdefault(rel, []).append(callback)
    
    def process_events(self):
        """Handle incoming UCWA events by updating the local data model."""
        for event in self.application.events():
            for sender in event['sender']:
                for ev in sender['events']:
                    ev = UCWAResource(ev, ucwa=self)
                    callbacks = self.callbacks.get(sender['rel'], [])
                    callbacks += self.callbacks.get(
                        (sender['rel'], ev['link']['rel']), [])
                    callbacks += self.callbacks.get(
                        (sender['rel'], ev['link']['rel'], ev['type']), [])
                    for callback in callbacks:
                        callback(self, ev)
        
    
if __name__ == "__main__":
    import getpass
    username = input("Username (email): ")
    password = getpass.getpass()

    #http_logger = urllib2.HTTPHandler(debuglevel=1)
    #opener = urllib2.build_opener(http_logger)
    #urllib2.install_opener(opener)

    try:
        l = LyncUCWA(username, password)
        c = l.search(username)
        #c = l.search('Rajesh')
        for contact in c:
            print(contact.contactPresence())

        # set available and listen for events
        l.set_available()

        def printer(u, event):
            print(event.communication['supportedMessageFormats'])
        l.register_callback(printer, 'communication', link_rel='communication')

        def accept_and_respond(u, event):
            print(getattr(event.messagingInvitation, 'from').name)
            print(event.messagingInvitation.message)
            # respond with acceptance
            event.accept(POST=True)
            event.messaging.sendMessage("Hi!")
        l.register_callback(accept_and_respond, 'communication',
                            link_rel='messagingInvitation',
                            ev_type='started')

        def print_conversation_state(u, event):
            print(event.state)
        l.register_callback(print_conversation_state,
                            'communication', link_rel='conversation')
        
        l.process_events()

    except HTTPError as e:
        print(e)
        print(e.read())
        

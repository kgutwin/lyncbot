from errbot import BotPlugin, botcmd, arg_botcmd, webhook

from lyncbot import web, ucwa


def check_logged_in(func):
    def wrap(self, message, args):
        frm = str(message.frm)
        if frm not in self.conns:
            return """Sorry, you're not logged in yet.
Please log in at http://127.0.0.1:3141/lyncbot"""
        return func(self, message, args)
    return wrap
        

class Lyncbot(BotPlugin, web.WebInterface):
    """
    Lync (Skype for Business) integration
    """

    def activate(self):
        super(Lyncbot, self).activate()
        self.conns = {}
        self.chats = {}
        self.current_chat = {}
        
    def deactivate(self):
        super(Lyncbot, self).deactivate()

    #def get_configuration_template(self):
    #    return {'EXAMPLE_KEY_1': "Example value",
    #            'EXAMPLE_KEY_2': ["Example", "Value"]
    #           }

    def check_configuration(self, configuration):
        super(Lyncbot, self).check_configuration(configuration)

    def callback_connect(self):
        pass

    def callback_message(self, message):
        frm = str(message.frm)
        if frm not in self.conns:
            return
        message_text = message.body
        if message.body.startswith('@'):
            dest, message_text = message.body.split(1)
            other = self.conns[frm].normalize_contact(dest[1:])
            chat = self.chats[frm].get(other)
        else:
            chat = self.current_chat.get(frm)
        if chat is None:
            self.send(message.frm, "Sorry - please open a chat first with "
                      "the !chat command.", in_reply_to=message)
            return
        chat.send(message_text)

    def lync_login(self, chatname, email, password):
        u = ucwa.LyncUCWA(email, password)
        self.conns[chatname] = u
        self.chats[chatname] = {}

        # be prepared to accept incoming chat invitations
        u.set_invitation_callback(
            lambda c: self.add_chat(c, chatname))
        
        # launch the event listener in a background thread
        u.thread = threading.Thread(target=u.process_events)
        u.setDaemon(True)
        u.start()
        return True

    def add_chat(self, chat, to):
        self.chats[to][chat.other[0]] = chat
        self.current_chat[to] = chat
        self.send(to, "New conversation from %s:" % (", ".join(chat.other)))
        if chat.invite_message:
            self.send(to, chat.invite_message)
    
    @botcmd
    @check_logged_in
    def contacts(self, message, args):
        """Displays a list of people to contact."""
        frm = str(message.frm)
        contact_str = ["%s (%s): %s" % (c.name, c.emailAddresses[0],
                                        c.contactPresence.availability)
                       for c in self.conns[frm].contacts()]
        return "\n".join(contact_str)
    
    @botcmd
    @check_logged_in
    def contact_status(self, message, args):
        """Displays the status of a contact."""
        # TODO: refactor to use LyncUCWA.search() so that we can pull status
        # for people who aren't in the contact list (and probably go faster)
        frm = str(message.frm)
        contact_str = ["%s (%s): %s" % (c.name, c.emailAddresses[0],
                                        c.contactPresence.availability)
                       for c in self.conns[frm].contacts(args)]
        return "\n".join(contact_str)
        
    @botcmd
    @check_logged_in
    def chat_with(self, message, args):
        """Starts a chat session with the desired recipient."""
        frm = str(message.frm)
        other = self.conns[frm].normalize_contact(args)
        if other in self.chats[frm]:
            self.current_chat[frm] = self.chats[frm][other]
            return
        chat = self.conns[frm].new_conversation([other])
        chat.set_inbound_callback(
            lambda m: self.inbound_chat_message(m, message.frm))
        self.chats[frm][other] = chat
        self.current_chat[frm] = chat
        return "Go ahead!"

    @botcmd
    @check_logged_in
    def chat_end(self, message, args):
        """Ends the current chat session or one specified."""
        frm = str(message.frm)
        if args:
            other = self.conns[frm].normalize_contact(args)
        else:
            chat = self.current_chat[frm]
            other = [k for k, v in self.conns[frm].items() if v == chat][0]
        if self.conns[frm][other] == self.current_chat[frm]:
            del(self.current_chat[frm])
        self.conns[frm][other].close()
        del(self.conns[frm][other])
        return "Chat with %s closed." % other
    
    def inbound_chat_message(self, message, to):
        """Posts an inbound chat message to the Errbot user."""
        self.send(to, message)

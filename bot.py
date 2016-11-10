from errbot import BotPlugin, botcmd, arg_botcmd, webhook

from lyncbot import web, ucwa

class Lyncbot(BotPlugin, web.WebInterface):
    """
    Lync (Skype for Business) integration
    """

    def activate(self):
        super(Lyncbot, self).activate()
        self.conns = {}
        
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
        pass

    def lync_login(self, chatname, email, password):
        u = ucwa.LyncUCWA(email, password)
        self.conns[chatname] = u
        return True
    
    @botcmd
    def contacts(self, message, args):
        """Displays a list of people to contact."""
        # TODO: build new decorator that automatically detects 'not logged in'
        frm = str(message.frm)
        if frm not in self.conns:
            return """Sorry, you're not logged in yet.
Please log in at http://127.0.0.1:3141/lyncbot"""
        contact_str = ["%s (%s): %s" % (c.name, c.emailAddresses[0],
                                        c.contactPresence.availability)
                       for c in self.conns[frm].contacts()]
        return "\n".join(contact_str)
    
    @botcmd
    def contact_status(self, message, args):
        """Displays the status of a contact."""
        # TODO: refactor to use LyncUCWA.search() so that we can pull status
        # for people who aren't in the contact list (and probably go faster)
        frm = str(message.frm)
        if frm not in self.conns:
            return """Sorry, you're not logged in yet.
Please log in at http://127.0.0.1:3141/lyncbot"""
        contact_str = ["%s (%s): %s" % (c.name, c.emailAddresses[0],
                                        c.contactPresence.availability)
                       for c in self.conns[frm].contacts(args)]
        return "\n".join(contact_str)
        
    @botcmd
    def chat(self, message, args):
        """Starts a chat session with the desired recipient."""
        return "Not implemented yet"

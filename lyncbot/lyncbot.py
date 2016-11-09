# -*- coding: utf-8 -*-

import .ucwa


def main(username, password):
    u = ucwa.LyncUCWA(username, password)
    for event in u.listen():
        # look for a messagingInvitation event
        # retrieve the invitation and send accept
        # look for a message event
        # retrieve the message

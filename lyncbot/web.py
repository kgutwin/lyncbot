from errbot import webhook

class WebInterface:
    @webhook('/lyncbot/login', raw=True)
    def login(self, request):
        status = self.lync_login(request.forms.get('chatname'),
                                 request.forms.get('email'),
                                 request.forms.get('password'))
        if status:
            return """<html><body>
<h1>Login</h1>
<p>Looks good! Return to the Errbot chat to continue.</p>
</body></html>"""
        else:
            return """<html><body>
<h1>Login</h1>
<p><b>Something went wrong.</b> Click <a href="/lyncbot">here</a> to return
to the login page and try again.</p>
</body></html>"""

    @webhook('/lyncbot')
    def index(self, request):
        return """<html><body>
<h1>Login</h1>
<form action="/lyncbot/login" method="POST">
  <div>Chat username: <input name="chatname"></div>
  <div>Lync username (email address): <input name="email"></div>
  <div>Password: <input name="password" type="password"></div>
  <input type="submit">
</form>
</body></html>
"""
    

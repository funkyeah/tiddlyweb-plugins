"""
Pretty Errors for TiddlyWeb
"""

import sys
import string

from tiddlyweb.model.bag import Bag
from tiddlyweb.model.recipe import Recipe
from tiddlyweb.model.tiddler import Tiddler
from tiddlyweb.store import NoRecipeError, NoBagError, NoTiddlerError
from tiddlyweb.web.http import HTTPExceptor, HTTPException


DEFAULT_TEXT = """
<html>
<head><title>Error: $status</title></head>
<body>
<p>There was a $status error with the following message:
    <blockquote>$message</blockquote>
There was also an error retrieving the error tiddler for 
this message.
</p>
</body>
</html>
"""


class PrettyHTTPExceptor(HTTPExceptor):

    def __call__(self, environ, start_response, exc_info=None):
        try:
            return self.application(environ, start_response)
        except HTTPException, exc:
            return self._send_response(environ, start_response, exc_info, exc)
        except:
            etype, value, traceb = sys.exc_info()
            exception_text = ''.join(traceback.format_exception(
                etype, value, traceb, None))
            print >> environ['wsgi.errors'], exception_text
            logging.warn(exception_text)

            exc = HTTPException(exception_text)
            exc.status = '500 server error'
            return self._send_response(environ, start_response,
                    sys.exc_info(), exc)

    def _send_response(self, environ, start_response, exc_info, exc):
        headers = [
                ('Content-type', 'text/html; charset=UTF-8')]
        status = exc.status.split(' ', 1)[0]
        status_tiddler = self._get_status_tiddler(environ, status)
        start_response(exc.status, headers, exc_info)
        text = self._format_tiddler(environ, status_tiddler, exc)
        return [text]

    def _format_tiddler(self, environ, status_tiddler, exc):
        template = string.Template(status_tiddler.text)
        info = {'status': exc.status, 'message': exc.output()}
        return template.substitute(**info)

    def _get_status_tiddler(self, environ, status):
        store = environ['tiddlyweb.store']
        recipe_name = environ['tiddlyweb.config'].get('prettyerror.recipe',
                '_errors')
        tiddler = Tiddler(status)
        try:
            recipe = store.get(Recipe(recipe_name))
            bag = determine_bag_from_recipe(recipe, tiddler, environ)
            tiddler.bag = bag.name
            tiddler = store.get(tiddler)
        except (NoRecipeError, NoBagError), exc:
            tiddler.text = DEFAULT_TEXT
        except (NoTiddlerError), exc:
            # If there is no default tiddler we get recursion error.
            tiddler = self._get_status_tiddler(environ, 'default')

        return tiddler



def init(config):
    config['server_response_filters'].insert(
            config['server_response_filters'].index(HTTPExceptor) + 1,
            PrettyHTTPExceptor)
    config['server_response_filters'].remove(HTTPExceptor)


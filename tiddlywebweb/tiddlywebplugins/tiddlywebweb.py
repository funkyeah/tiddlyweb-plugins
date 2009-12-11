"""
A StorageInterface that stores in another TiddlyWeb.
"""

import httplib2
import logging
import simplejson
import urllib

from base64 import b64encode

from tiddlyweb.model.policy import UserRequiredError
from tiddlyweb.model.bag import Bag
from tiddlyweb.model.recipe import Recipe
from tiddlyweb.model.tiddler import Tiddler
from tiddlyweb.serializer import Serializer
from tiddlyweb.store import NoBagError, NoRecipeError, NoTiddlerError, NoUserError
from tiddlyweb.stores import StorageInterface

# XXX can't remember why this was needed :(
#urllib.always_safe = urllib.always_safe.replace('.', '')

class TiddlyWebWebError(Exception):
    pass

class Store(StorageInterface):

    recipes_url = '/recipes'
    bags_url = '/bags'

    recipe_url = '/recipes/%s'
    recipe_tiddlers_url = '/recipes/%s/tiddlers'

    bag_url = '/bags/%s'
    bag_tiddlers_url = '/bags/%s/tiddlers'

    tiddler_url = '/bags/%s/tiddlers/%s'
    revisions_url = '/bags/%s/tiddlers/%s/revisions'
    revision_url = '/bags/%s/tiddlers/%s/revisions/%s'

    search_url = '/search?q=%s'

    def __init__(self, environ={}):
        self.environ = environ
        #self.http = httplib2.Http('.cache')
        server_info = self.environ['tiddlyweb.config']['server_store'][1]
        self._base = server_info['server_base']
        user = server_info.get('user', None)
        password = server_info.get('password', None)
        cache = server_info.get('use_cache', False)
        if cache:
            self.http = httplib2.Http('.cache')
        else:
            self.http = httplib2.Http()
        self.authorization = None
        if user and password:
            self.authorization = b64encode('%s:%s' % (user, password))
        self.serializer = Serializer('json')

    def _request(self, method, url, data=None):
        headers = {}
        if method == 'GET':
            headers = {'Accept': 'application/json'}
        else:
            headers = {'Content-Type': 'application/json'}
        if self.authorization:
            headers['Authorization'] = 'Basic %s' % self.authorization
        url = self._server_base() + url
        return self.http.request(url, method=method, headers=headers, body=data)

    def _server_base(self):
        return self._base

    def _is_success(self, response):
        return response['status'].startswith('20') or response['status'] == '304'

    def _any_delete(self, url, target_object):
        response, content = self._request('DELETE', url)
        if not self._is_success(response):
            raise TiddlyWebWebError('%s: %s' % (response['status'], content))

    def _any_get(self, url, target_object):
        response, content = self._request('GET', url)
        if self._is_success(response):
            if response['content-type'].startswith('application/json'):
                self.serializer.object = target_object
                self.serializer.from_string(content)
            else:
                # XXX got a binary tiddler
                pass
        elif response['status'] == '401':
            raise UserRequiredError('you do not have permission')
        else:
            print response, content
            raise TiddlyWebWebError('%s: %s' % (response['status'], content))

    def _any_put(self, url, target_object):
        self.serializer.object = target_object
        data = self.serializer.to_string()
        response, content = self._request('PUT', url, data)
        if not self._is_success(response):
            raise TiddlyWebWebError('%s: %s' % (response['status'], content))

    def doit(self, url, object, method, exception):
        try:
            method(url, object)
        except TiddlyWebWebError, e:
            raise exception(e)

    def recipe_delete(self, recipe):
        url = self.recipe_url % _encode_name(recipe.name)
        self.doit(url, recipe, self._any_delete, NoRecipeError)

    def recipe_get(self, recipe):
        url = self.recipe_url % _encode_name(recipe.name)
        self.doit(url, recipe, self._any_get, NoRecipeError)
        return recipe

    def recipe_put(self, recipe):
        url = self.recipe_url % _encode_name(recipe.name)
        self.doit(url, recipe, self._any_put, NoRecipeError)

    def bag_delete(self, bag):
        url = self.bag_url % _encode_name(bag.name)
        self.doit(url, bag, self._any_delete, NoBagError)

    def bag_get(self, bag):
        url = self.bag_url % _encode_name(bag.name)
        self.doit(url, bag, self._any_get, NoBagError)
        if not (hasattr(bag, 'skinny') and bag.skinny):
            url = self.bag_tiddlers_url % bag.name
            response, content = self._request('GET', url)
            if self._is_success(response):
                tiddlers = simplejson.loads(content)
                for tiddler in tiddlers:
                    bag.add_tiddler(Tiddler(tiddler['title']))
        return bag

    def bag_put(self, bag):
        url = self.bag_url % _encode_name(bag.name)
        self.doit(url, bag, self._any_put, NoBagError)

    def tiddler_delete(self, tiddler):
        url = self.tiddler_url % (_encode_name(tiddler.bag), _encode_name(tiddler.title))
        self.doit(url, tiddler, self._any_delete, NoTiddlerError)

    def tiddler_get(self, tiddler):
        if tiddler.revision:
            url = self.revision_url % (_encode_name(tiddler.bag), _encode_name(tiddler.title), tiddler.revision)
        else:
            url = self.tiddler_url % (_encode_name(tiddler.bag), _encode_name(tiddler.title))
        self.doit(url, tiddler, self._any_get, NoTiddlerError)
        return tiddler

    def tiddler_put(self, tiddler):
        url = self.tiddler_url % (_encode_name(tiddler.bag), _encode_name(tiddler.title))
        tiddler.revision = self._tiddler_revision(tiddler) + 1
        self.doit(url, tiddler, self._any_put, NoTiddlerError)
        self.tiddler_written(tiddler)

    def _tiddler_revision(self, tiddler, index=0):
        """
        Calculate the revision filename for the tiddler revision
        we want.
        """
        revision = 0
        if tiddler.revision:
            revision = tiddler.revision
        else:
            try:
                revisions = self.list_tiddler_revisions(tiddler)
                if revisions:
                    revision = revisions[index]
            except NoTiddlerError:
                pass
        return int(revision)

    def user_get(self, user):
        """No URLs for users, yet."""
        pass

    def user_put(self, user):
        """No URLs for users, yet."""
        pass

    def list_recipes(self):
        url = self.recipes_url
        response, content = self._request('GET', url)
        if self._is_success(response):
            recipes = simplejson.loads(content)
            return [Recipe(recipe) for recipe in recipes]
        else:
            return []

    def list_bags(self):
        url = self.bags_url
        response, content = self._request('GET', url)
        if self._is_success(response):
            bags = simplejson.loads(content)
            return [Bag(bag) for bag in bags]
        else:
# XXX um, so, like, some error handling would be good here
            return []

    def list_tiddler_revisions(self, tiddler):
        url = self.revisions_url % (_encode_name(tiddler.bag), _encode_name(tiddler.title))
        response, content = self._request('GET', url)
        if self._is_success(response):
            revisions = simplejson.loads(content)
            revision_ids = [revision['revision'] for revision in revisions]
            #revision_ids.reverse()
            return revision_ids
        else:
            # XXX better error handling than this would be nice
            raise NoTiddlerError


    def search(self, search_query):
        def _make_tiddler(result_dict):
            tiddler = Tiddler(result_dict['title'])
            tiddler.bag = result_dict['bag']
            tiddler.revision = result_dict['revision']
            return tiddler
        url = self.search_url % _encode_name(search_query)
        response, content = self._request('GET', url)
        if self._is_success(response):
            results = simplejson.loads(content)
            return [_make_tiddler(result) for result in results]
        else:
            return []

def _encode_name(name):
    name = urllib.quote(name.encode('UTF-8'), safe='') # encode /
    logging.debug(name)
    return name

def test_me():
    environ = {'tiddlyweb.config': {}}
    environ['tiddlyweb.config']['server_store'] = \
            ['tiddlywebplugins.tiddlywebweb', {'use_cache': True, 'server_base':'http://tiddlyweb.peermore.com/wiki'}]

    store = Store(environ)
    recipes = store.list_recipes()
    print 'Recipes: ', [recipe.name for recipe in recipes]
    bags = store.list_bags()
    print 'Bags: ', [bag.name for bag in bags]

    for recipe in recipes:
        try:
            store.recipe_get(recipe)
        except NoRecipeError:
            pass
        print 'Recipe name:', recipe.name.encode('UTF-8')
        print 'Recipe recipe:'
        print recipe

    for bag in bags:
        try:
            store.bag_get(bag)
        except NoBagError:
            pass
        print 'Bag name: ', bag.name.encode('UTF-8')
        print 'Bag Tiddlers:'
        for tiddler in bag.list_tiddlers():
            print 'tiddler: %s' % tiddler.title.encode('UTF-8')

    for bag in bags:
        for tiddler in bag.list_tiddlers():
            try:
                store.tiddler_get(tiddler)
            except NoTiddlerError:
                pass
            print 'Tiddler title:', tiddler.title.encode('UTF-8')
            print 'modified:', tiddler.modified
            if tiddler.type != None and tiddler.type != 'None':
                print '#### got a special type: %s' % tiddler.type
            else:
                print tiddler.text.encode('UTF-8')
            print

if __name__ == '__main__':
    test_me()


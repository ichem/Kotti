from datetime import datetime
from UserDict import DictMixin

from sqlalchemy import Table
from sqlalchemy import Column
from sqlalchemy import Unicode
from sqlalchemy import DateTime
from sqlalchemy.sql.expression import or_
from sqlalchemy.orm import mapper
from sqlalchemy.orm.exc import NoResultFound
from pyramid.location import lineage
from pyramid.security import Allow
from pyramid.security import ALL_PERMISSIONS

from kotti import configuration
from kotti.resources import DBSession
from kotti.resources import metadata
from kotti.util import JsonType

class PersistentACL(object):
    """Manages access to ``self._acl`` which is a JSON- serialized
    representation of ``self.__acl__``.
    """
    ALL_PERMISSIONS_SERIALIZED = '__ALL_PERMISSIONS__'

    @staticmethod
    def _deserialize_ace(ace):
        ace = list(ace)
        if ace[2] == PersistentACL.ALL_PERMISSIONS_SERIALIZED:
            ace[2] = ALL_PERMISSIONS
        return tuple(ace)

    @staticmethod
    def _serialize_ace(ace):
        ace = list(ace)
        if ace[2] == ALL_PERMISSIONS:
            ace[2] = PersistentACL.ALL_PERMISSIONS_SERIALIZED
        return ace

    def _get_acl(self):
        if self._acl is not None:
            acl = self._default_acl() + self._acl
            return [self._deserialize_ace(ace) for ace in acl]
        else:
            raise AttributeError('__acl__')

    def _set_acl(self, acl):
        self._acl = [self._serialize_ace(ace) for ace in acl]

    def _del_acl(self):
        if self._acl is not None:
            self._acl = None
        else:
            raise AttributeError('__acl__')

    __acl__ = property(_get_acl, _set_acl, _del_acl)

    def _default_acl(self):
        # ACEs that will be put on top, no matter what
        # XXX Not sure this is a good idea.
        return [
            (Allow, 'group:admins', ALL_PERMISSIONS),
            ]

def list_groups_raw(id, context):
    groups = getattr(context, '__groups__', None)
    if groups is not None:
        return groups.get(id, set())
    else:
        return set()

def list_groups(id, context, _seen=None):
    groups = set()
    if _seen is None:
        _seen = set()

    # Add groups from principal db:
    principal = get_principals().get(id)
    if principal is not None:
        groups.update(principal.groups)

    # Add local groups:
    for item in lineage(context):
        groups.update(list_groups_raw(id, item))

    # Groups may be nested:
    new_groups = groups - _seen
    for groupid in new_groups:
        _seen.add(groupid)
        groups.update(list_groups(groupid, context, _seen))
    return list(groups)

def set_groups(id, context, groups_to_set):
    groups = getattr(context, '__groups__', None)
    if groups is None:
        groups = {}
    groups[id] = list(groups_to_set)
    context.__groups__ = groups

def list_groups_callback(id, request):
    if not is_user(id):
        return None
    if id in get_principals():
        return list_groups(id, request.context)

def get_principals():
    return configuration['kotti.principals'][0]

def is_user(principal):
    if not isinstance(principal, basestring):
        principal = principal.id
    return not principal.startswith('group:')

class Principal(object):
    def __init__(self, id, title=u"", groups=()):
        self.id = id
        self.title = title
        self.groups = groups
        self.creation_date = datetime.now()

class Principals(DictMixin):
    """Kotti's default principal database.

    Promises dict-like access to user profiles, and a 'search' method
    for finding users.

    This is a default implementation that may be replaced by using the
    'kotti.principals' configuration variable.
    """
    factory = Principal

    def __getitem__(self, key):
        key = unicode(key)
        session = DBSession()
        try:
            return session.query(
                self.factory).filter(self.factory.id==key).one()
        except NoResultFound:
            raise KeyError(key)

    def __setitem__(self, key, principal):
        key = unicode(key)
        session = DBSession()
        if isinstance(principal, dict):
            profile = self.factory(**principal)
        session.add(profile)

    def __delitem__(self, key):
        key = unicode(key)
        session = DBSession()
        try:
            principal = session.query(
                self.factory).filter(self.factory.id==key).one()
            session.delete(principal)
        except NoResultFound:
            raise KeyError(key)

    def iterkeys(self):
        session = DBSession()
        for (principal,) in session.query(self.factory.id):
            yield principal

    def keys(self):
        return list(self.iterkeys())

    def search(self, term):
        if not term:
            return []
        session = DBSession()
        query = session.query(self.factory)
        query.filter(or_(
            self.factory.id == term,
            self.factory.title == term,
            self.factory.email == term,
            ))
        return query

principals = Principals()

principals_table = Table('principals', metadata,
    Column('id', Unicode(100), primary_key=True),
    Column('title', Unicode(100), nullable=False),
    Column('email', Unicode(100)),
    Column('groups', JsonType(), nullable=False),
    Column('creation_date', DateTime(), nullable=False),
)

mapper(Principal, principals_table, order_by=principals_table.c.id)

# Note how roles are really groups too.  The only special thing
# about them is that they're defined by Kotti and appear in the
# user interface in the sharing tab.
ROLES = [
    Principal(u'group:editors', u'Editors'),
    Principal(u'group:managers', u'Managers'),
    Principal(u'group:admins', u'Administrators'),
    ]

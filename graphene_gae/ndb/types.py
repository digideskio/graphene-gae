import inspect
import six
from collections import OrderedDict

from graphene.types.structures import Structure

from google.appengine.ext import ndb

from graphene import ObjectType, Field, NonNull
from graphene.types.objecttype import ObjectTypeMeta, merge, yank_fields_from_attrs
from graphene.utils.is_base_type import is_base_type
from graphene.types.options import Options
from graphene.relay import is_node

from graphene_gae.ndb.converter import convert_ndb_property

__author__ = 'ekampf'


class Registry(object):
    REGISTRY = {}

    def register(self, cls):
        # TODO: add checks that cls is of the right type
        self.REGISTRY[cls._meta.model] = cls

    @classmethod
    def get_type_for_model(cls, model):
        return cls.REGISTRY.get(model)


class NdbObjectTypeMeta(ObjectTypeMeta):
    REGISTRY = {}

    def __new__(mcs, name, bases, attrs):
        if not is_base_type(bases, NdbObjectTypeMeta):
            return type.__new__(mcs, name, bases, attrs)

        options = Options(
            attrs.pop('Meta', None),
            name=name,
            description=attrs.pop('__doc__', None),
            model=None,
            local_fields=None,
            only_fields=(),
            exclude_fields=(),
            id='id',
            interfaces=(),
            registry=None
        )

        if not options.model:
            raise Exception('NdbObjectType %s must have a model in the Meta class attr' % name)

        if not inspect.isclass(options.model) or not issubclass(options.model, ndb.Model):
            raise Exception('Provided model in %s is not an NDB model' % name)

        new_cls = ObjectTypeMeta.__new__(mcs, name, bases, dict(attrs, _meta=options))
        mcs.register(new_cls)

        ndb_fields = mcs.fields_for_ndb_model(options)
        options.ndb_fields = yank_fields_from_attrs(
            ndb_fields,
            _as=Field,
        )
        options.fields = merge(
            options.interface_fields,
            options.ndb_fields,
            options.base_fields,
            options.local_fields
        )

        return new_cls

    @classmethod
    def register(mcs, object_type_meta):
        mcs.REGISTRY[object_type_meta._meta.model] = object_type_meta

    @staticmethod
    def fields_for_ndb_model(options):
        ndb_model = options.model
        only_fields = options.only_fields
        already_created_fields = {name for name, _ in options.local_fields.iteritems()}

        ndb_fields = OrderedDict()
        for prop_name, prop in ndb_model._properties.iteritems():
            name = prop._code_name

            is_not_in_only = only_fields and name not in only_fields
            is_excluded = name in options.exclude_fields or name in already_created_fields
            if is_not_in_only or is_excluded:
                continue

            results = convert_ndb_property(prop)
            if not results:
                continue

            if not isinstance(results, list):
                results = [results]

            for r in results:
                ndb_fields[r.name] = r.field

        return ndb_fields


class NdbObjectType(six.with_metaclass(NdbObjectTypeMeta, ObjectType)):
    @classmethod
    def is_type_of(cls, root, context, info):
        if isinstance(root, cls):
            return True

        if not cls.is_valid_ndb_model(type(root)):
            raise Exception(('Received incompatible instance "{}".').format(root))

        return type(root) == cls._meta.model

    @classmethod
    def get_node(cls, urlsafe_key, *_):
        model = cls._meta.model
        try:
            key = ndb.Key(urlsafe=urlsafe_key)
        except:
            return None

        assert key.kind() == model.__name__
        return key.get()

    def resolve_id(root, args, context, info):
        graphene_type = info.parent_type.graphene_type
        if is_node(graphene_type):
            return root.__mapper__.primary_key_from_instance(root)[0]

        return getattr(root, graphene_type._meta.id, None)

    @staticmethod
    def is_valid_ndb_model(model):
        return inspect.isclass(model) and issubclass(model, ndb.Model)


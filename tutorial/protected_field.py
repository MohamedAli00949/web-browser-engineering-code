from constants import *

class ProtectedField:
    def __init__(self, obj, name, parent=None, dependencies=None, invalidations=None):
        self.obj = obj
        self.name = name
        self.parent = parent
        self.value = None
        self.dirty = True
        self.invalidations = set()

        self.frozen_dependencies = dependencies != None
        if dependencies != None:
            for dependency in dependencies:
                dependency.invalidations.add(self)

        self.frozen_invalidations = invalidations != None
        if invalidations != None:
            assert self.name == "children"
            for invalidation in invalidations:
                self.invalidations.add(invalidation)

    def mark(self):
        if self.dirty:
            return
        self.dirty = True
        self.set_ancestor_dirty_bits()

    def get(self):
        assert not self.dirty
        return self.value

    def set(self, value):
        if self.value != None:
            print("Change", self)
        if value != self.value:
            self.notify()
        self.value = value
        self.dirty = False

    def notify(self):
        for field in self.invalidations:
            field.mark()
        self.set_ancestor_dirty_bits()

    def read(self, notify):
        if notify.frozen_dependencies:
            assert notify in self.invalidations
        else:
            self.invalidations.add(notify)

        return self.get()

    def copy(self, field):
        self.set(field.read(notify=self))

    def set_ancestor_dirty_bits(self):
        parent = self.parent
        while parent and not parent.has_dirty_descendants:
            parent.has_dirty_descendants = True
            parent = parent.parent

    def set_dependencies(self, dependencies):
        for dependency in dependencies:
            dependency.invalidations.add(self)
        self.frozen_dependencies = True

    def __repr__(self):
        return "ProtectedField({}, {})".format(
            self.obj.node if hasattr(self.obj, "node") else self.obj, self.name
        )

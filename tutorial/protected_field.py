
class ProtectedField:
    def __init__(self):
        self.value = None
        self.dirty = True
        self.invalidations = set()
    
    def mark(self):
        if self.dirty: return
        self.dirty = True

    def get(self):
        assert not self.dirty
        return self.value
    
    def set(self, value):
        self.notify()
        self.value = value
        self.dirty = False
    
    def notify(self):
        for field in self.invalidations:
            field.mark()

    def read(self, notify):
        self.invalidations.add(notify)
        return self.get()
    
    def copy(self, field):
        self.set(field.read(notify=self))

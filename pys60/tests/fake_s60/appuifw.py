"""Fake appuifw for PC tests: every attribute is a harmless dummy."""
FAKE = 1


class _Dummy(object):
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return None

    def __getattr__(self, name):
        return _Dummy()

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

    def __nonzero__(self):
        return False


app = _Dummy()
app.title = u''
app.body = None
app.menu = []
app.exit_key_handler = None
app.screen = 'normal'


def note(*a, **k):
    return None


def query(*a, **k):
    return None


def popup_menu(*a, **k):
    return None


def selection_list(*a, **k):
    return None


def multi_selection_list(*a, **k):
    return []


class Listbox(_Dummy):
    def current(self):
        return 0

    def set_list(self, *a, **k):
        return None

    def bind(self, *a, **k):
        return None


class Text(_Dummy):
    def get(self):
        return u''

    def set(self, *a):
        return None

    def add(self, *a):
        return None

    def clear(self):
        return None


class Form(_Dummy):
    pass


class Canvas(_Dummy):
    pass


class Content_handler(_Dummy):
    pass


EEventKeyDown = 3
EEventKey = 1
EEventKeyUp = 2
FFormEditModeOnly = 1
FFormDoubleSpaced = 4


def __getattr__(name):  # module-level fallback (py3.7+ only; harmless on py2)
    return _Dummy()

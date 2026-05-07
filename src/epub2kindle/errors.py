class Epub2KindleError(Exception):
    pass


class EncryptedEpubError(Epub2KindleError):
    pass


class MalformedEpubError(Epub2KindleError):
    pass


class OutputDirError(Epub2KindleError):
    pass


class ConversionError(Epub2KindleError):
    pass

class Epub2KindleError(Exception):
    pass


class EncryptedEpubError(Epub2KindleError):
    pass


class MalformedEpubError(Epub2KindleError):
    pass


class KindleGenNotFoundError(Epub2KindleError):
    def __init__(self):
        super().__init__(
            "kindlegen not found on PATH.\n"
            "Obtain it from the Internet Archive (kindlegen_linux_2.6_i386_v2_9.tar.gz)\n"
            "and place the binary somewhere on your PATH, e.g. ~/.local/bin/kindlegen"
        )


class SevenZipNotFoundError(Epub2KindleError):
    def __init__(self):
        super().__init__(
            "7z not found on PATH. Install with: sudo apt install p7zip-full"
        )


class OutputDirError(Epub2KindleError):
    pass


class KCCImportError(Epub2KindleError):
    def __init__(self, cause: Exception):
        super().__init__(
            f"Failed to import kindlecomicconverter: {cause}\n"
            "Make sure KCC is installed: "
            "pip install 'kindlecomicconverter @ git+https://github.com/ciromattia/kcc.git@<SHA>'"
        )
        self.__cause__ = cause


class ConversionError(Epub2KindleError):
    pass

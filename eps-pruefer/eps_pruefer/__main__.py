import sys


def run() -> int:
    if "--cli" in sys.argv[1:]:
        from .cli import main

        return main(sys.argv[1:])
    from .gui import main

    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(run())

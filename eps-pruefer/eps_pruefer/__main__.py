import sys


def run() -> int:
    args = sys.argv[1:]
    if "--cli" in args:
        from .cli import main

        return main(args)
    if "--klassisch" in args:  # Oberfläche v1
        from .gui import main

        return main([a for a in args if a != "--klassisch"])
    from .gui2 import main

    return main(args)


if __name__ == "__main__":
    sys.exit(run())

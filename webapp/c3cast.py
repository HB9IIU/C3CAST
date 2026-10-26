"""C3CAST.exe entry point: the web app, or one of its helper processes (C3CAST.exe --worker NAME ...)."""
import sys


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        name, rest = sys.argv[2], sys.argv[3:]
        if name == "runner":                    # upstream tx_dvbs.py with a clean stop (the transmitter)
            import runner
            runner.main(rest)
        elif name == "stream_tx":               # clock / picture / camera -> ffmpeg -> runner
            import stream_tx
            sys.exit(stream_tx.main(rest))
        elif name == "esptool":                 # the flasher
            sys.argv = ["esptool"] + rest
            import esptool
            esptool._main()
        else:
            sys.exit(f"unknown worker: {name}")
        return
    import app
    app.serve()


if __name__ == "__main__":
    main()

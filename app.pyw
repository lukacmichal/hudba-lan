import os
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.multimedia.*=false")

from music_player.app import main

if __name__ == "__main__":
    main()
